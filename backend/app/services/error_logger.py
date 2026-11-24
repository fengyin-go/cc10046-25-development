"""错误日志领域服务：记录采集错误，并维护错误处置差异复核。

差异复核的背景：错误记录详情里的实际处理状态（``status`` / ``处理状态``）可能与
采集错误处理数据回传的旧处理字段（``旧处理状态`` / ``旧处置动作``）对不上。
本服务按追踪号把两栏数据逐号对照，生成错误处置差异视图，供值班员领取并复核。

关键约定：
- 领取与复核只改差异复核表，绝不回写错误记录本身，因此复核不会重新触发实际错误处理。
- 领取在进程内加锁并做状态校验，两个值班员同时领取同一追踪号时只有一人成功。
- 差异列表每次实时计算，待领列表随错误记录实际结案（两栏重新一致）自动同步更新；
  已复核的历史差异保留快照，仍可在「全部」范围查询。
"""
from __future__ import annotations

import threading
import time
from typing import Any

from app.services.base import BaseModuleService
from app.store import store

# 差异复核表在内存仓库中的模块 key。
REVIEW_MODULE = "error_disposition_review"

# 旧处理数据两栏 + 实际确认来源字段名。
LEGACY_STATUS_FIELD = "旧处理状态"
LEGACY_ACTION_FIELD = "旧处置动作"
SOURCE_FIELD = "实际确认来源"

DIFF_CONFLICT = "状态冲突"
DIFF_MISSING = "旧处置缺失"

SCOPE_OPEN = "open"          # 待复核 = 待领取 + 复核中
SCOPE_UNCLAIMED = "unclaimed"
SCOPE_CLAIMED = "claimed"
SCOPE_REVIEWED = "reviewed"
SCOPE_ALL = "all"


class ErrorLoggerService(BaseModuleService):
    MODULE = "error_logger"
    ENTITY = "错误日志"
    OPERATION_TERM = "采集"
    LIST_FIELDS = [
        "错误码", "错误信息", "来源模块", "发生时间", "追踪号", "严重级别", "处理状态",
        "关联任务", LEGACY_STATUS_FIELD, LEGACY_ACTION_FIELD, SOURCE_FIELD,
    ]
    REQUIRED_FIELDS = ["错误码", "错误信息", "来源模块"]
    STATUS_ORDER = ["未处理", "处理中", "已解决", "已忽略"]
    ACTION_RULES = {"开始处理": "处理中", "标记解决": "已解决", "标记忽略": "已忽略", "重新打开": "未处理"}
    NEGATIVE_ACTIONS = ["标记忽略"]

    # 类级锁：不同服务实例（资源路由 / 业务链路）共享同一把领取锁。
    _claim_lock = threading.Lock()

    # ------------------------------------------------------------------ 录入
    def domain_log_error(self, error_code: str, error_message: str,
                         source_module: str, trace_id: str = "",
                         severity: str = "error") -> dict:
        """记录采集错误并返回日志条目。

        新录入的错误还没有任何旧处理数据，两栏旧值留空，后续会进入差异视图的
        「旧处置缺失」清单；实际确认来源标记为可靠性检查录入。
        """
        rows = store.rows(self.MODULE)
        new_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry = {
            "id": new_id,
            "错误码": error_code,
            "错误信息": error_message,
            "来源模块": source_module,
            "发生时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "追踪号": trace_id or f"TRACE-{new_id}",
            "严重级别": severity,
            "处理状态": "未处理",
            "关联任务": source_module,
            "status": "未处理",
            "pending": True,
            "abnormal": severity == "error",
            LEGACY_STATUS_FIELD: "",
            LEGACY_ACTION_FIELD: "",
            SOURCE_FIELD: "可靠性检查录入",
        }
        rows.append(entry)
        return entry

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """人工登记错误：旧处理两栏不允许手工预填，统一从空值开始对账。"""
        entry, missing = super().create_entry(values)
        if entry is not None:
            entry[LEGACY_STATUS_FIELD] = ""
            entry[LEGACY_ACTION_FIELD] = ""
            entry[SOURCE_FIELD] = values.get(SOURCE_FIELD) or "人工登记"
        return entry, missing

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        """在错误详情页执行处置动作。

        首次处置时把动作前的实际状态冻结进旧处理字段，作为对账旧值；之后再次流转
        不覆盖旧值，保证两栏旧值稳定可对账。实际确认来源记录到具体详情页动作。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None, f"{self.ENTITY} {entry_id} 不存在或已归档"
        if not str(entry.get(LEGACY_STATUS_FIELD) or "").strip():
            entry[LEGACY_STATUS_FIELD] = entry.get("status", "未处理")
            entry[LEGACY_ACTION_FIELD] = action
        entry[SOURCE_FIELD] = f"错误详情页-{action}"
        return super().run_action(entry_id, action)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """详情读取：附带该追踪号的差异复核归属，供详情页核对归属与原处置动作。"""
        entry = super().get_entry(entry_id)
        if entry is None:
            return None
        review = self._find_review(str(entry.get("追踪号", "")))
        if review is not None:
            entry["归属值班员"] = review.get("归属值班员", "")
            entry["领取时间"] = review.get("领取时间", "")
            entry["复核状态"] = review.get("复核状态", "")
            entry["复核时间"] = review.get("复核时间", "")
            entry["复核备注"] = review.get("复核备注", "")
        else:
            entry.setdefault("归属值班员", "")
            entry.setdefault("复核状态", "")
        return entry

    # ------------------------------------------------------------ 差异视图
    def list_dispositions(
        self,
        *,
        scope: str = SCOPE_OPEN,
        keyword: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """按追踪号返回错误处置差异视图，支持范围筛选与分页。

        scope 取值：unclaimed 待领取 / claimed 复核中 / reviewed 已复核 /
        all 全部（含历史）/ open 待复核（默认，待领取+复核中）。
        """
        rows = self._compute_dispositions()
        if keyword:
            needle = keyword.strip().casefold()
            rows = [row for row in rows if needle in str(row.get("追踪号", "")).casefold()]
        scoped = self._filter_scope(rows, scope)
        total = len(scoped)
        start = (page - 1) * size
        return scoped[start:start + size], total

    def disposition_snapshot(self) -> dict[str, Any]:
        """差异复核口径快照：统计数字与明细列表来自同一次实时计算，保证同口径。"""
        rows = self._compute_dispositions()
        unclaimed = self._filter_scope(rows, SCOPE_UNCLAIMED)
        claimed = self._filter_scope(rows, SCOPE_CLAIMED)
        reviewed = self._filter_scope(rows, SCOPE_REVIEWED)
        return {
            "待领取": len(unclaimed),
            "复核中": len(claimed),
            "待复核": len(unclaimed) + len(claimed),
            "已复核": len(reviewed),
            "差异总数": len(rows),
            # 概览领取入口直接消费这份待领明细，与上面的统计同一次计算、同一实际范围。
            "open_items": unclaimed,
        }

    def claim_disposition(self, trace_id: str, operator: str) -> tuple[dict[str, Any] | None, str]:
        """领取一条差异追踪号。加锁 + 状态校验，并发领取只有一人成功。"""
        operator = (operator or "").strip()
        if not operator:
            return None, "领取时必须填写值班员"
        trace_id = trace_id.strip()
        with self._claim_lock:
            live = {str(row.get("追踪号", "")): row for row in self._compute_live_diffs()}
            if trace_id not in live:
                return None, f"追踪号 {trace_id} 当前不在待领差异列表"
            existing = self._find_review(trace_id)
            if existing is not None:
                if existing.get("复核状态") == "已复核":
                    return None, f"追踪号 {trace_id} 已完成复核，无需重复领取"
                return None, f"追踪号 {trace_id} 已由 {existing.get('归属值班员')} 领取"
            review_rows = store.rows(REVIEW_MODULE)
            new_id = max((int(row.get("id", 0)) for row in review_rows), default=0) + 1
            diff = live[trace_id]
            review_rows.append({
                "id": new_id,
                "追踪号": trace_id,
                "复核状态": "已领取",
                "归属值班员": operator,
                "领取时间": time.strftime("%Y-%m-%d %H:%M:%S"),
                "复核时间": "",
                "复核备注": "",
                "详情状态快照": diff.get("详情状态", ""),
                "旧处理状态快照": diff.get("旧处理状态", ""),
                "旧处置动作快照": diff.get("旧处置动作", ""),
                "实际确认来源快照": diff.get("实际确认来源", ""),
                "差异类型快照": diff.get("差异类型", ""),
            })
        return self._find_review(trace_id), f"追踪号 {trace_id} 已领取，归属 {operator}"

    def review_disposition(
        self, trace_id: str, operator: str, remark: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """完成差异复核。

        只更新差异复核表，不修改任何错误记录字段，因此不会重新触发实际错误处理。
        只有归属值班员本人可以提交复核。
        """
        operator = (operator or "").strip()
        trace_id = trace_id.strip()
        review = self._find_review(trace_id)
        if review is None:
            return None, f"追踪号 {trace_id} 尚未领取，不能复核"
        if review.get("复核状态") == "已复核":
            return None, f"追踪号 {trace_id} 已复核完成"
        if review.get("归属值班员") != operator:
            return None, f"追踪号 {trace_id} 归属 {review.get('归属值班员')}，{operator} 无权复核"
        before = self._snapshot_error_rows(trace_id)
        review["复核状态"] = "已复核"
        review["复核时间"] = time.strftime("%Y-%m-%d %H:%M:%S")
        review["复核备注"] = remark.strip()
        # 防御性断言：复核前后错误记录保持一致，证明复核不触碰实际错误处理。
        after = self._snapshot_error_rows(trace_id)
        if before != after:  # pragma: no cover - 业务上不应发生
            raise RuntimeError("差异复核意外改动了错误记录")
        return review, f"追踪号 {trace_id} 复核完成"

    # ------------------------------------------------------------ 内部计算
    def _compute_live_diffs(self) -> list[dict[str, Any]]:
        """实时扫描错误记录，按追踪号对照两栏数据，只保留对不上的差异。"""
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in store.rows(self.MODULE):
            grouped.setdefault(str(row.get("追踪号", "")), []).append(row)
        diffs: list[dict[str, Any]] = []
        for trace_id, rows in grouped.items():
            rows = sorted(rows, key=lambda item: int(item.get("id", 0)))
            latest = rows[-1]
            actual_status = str(latest.get("status", ""))
            legacy_status = str(latest.get(LEGACY_STATUS_FIELD, "") or "")
            legacy_action = str(latest.get(LEGACY_ACTION_FIELD, "") or "")
            source = str(latest.get(SOURCE_FIELD, "") or "")
            if not legacy_status.strip():
                diff_type = DIFF_MISSING
            elif legacy_status != actual_status:
                diff_type = DIFF_CONFLICT
            else:
                # 两栏一致：实际已结案，差异自动消失（待领列表随之同步更新）。
                continue
            diffs.append({
                "追踪号": trace_id,
                "错误日志id": [int(item.get("id", 0)) for item in rows],
                "详情状态": actual_status,
                "处理状态": str(latest.get("处理状态", "")),
                LEGACY_STATUS_FIELD: legacy_status,
                LEGACY_ACTION_FIELD: legacy_action,
                SOURCE_FIELD: source,
                "差异类型": diff_type,
                "发生时间": str(latest.get("发生时间", "")),
                "错误码": str(latest.get("错误码", "")),
            })
        return sorted(diffs, key=lambda item: item["追踪号"])

    def _compute_dispositions(self) -> list[dict[str, Any]]:
        """实时差异 + 复核归属 + 已复核历史快照合并成完整视图。"""
        live = {str(row["追踪号"]): row for row in self._compute_live_diffs()}
        merged: list[dict[str, Any]] = []
        for trace_id, diff in live.items():
            review = self._find_review(trace_id)
            merged.append(self._join_review(diff, review))
        # 已核对的历史差异即使错误记录被归档/对平，也凭快照继续可查。
        live_traces = set(live)
        for review in store.rows(REVIEW_MODULE):
            trace_id = str(review.get("追踪号", ""))
            if trace_id in live_traces:
                continue
            merged.append({
                "追踪号": trace_id,
                "错误日志id": [],
                "详情状态": review.get("详情状态快照", ""),
                "处理状态": review.get("详情状态快照", ""),
                LEGACY_STATUS_FIELD: review.get("旧处理状态快照", ""),
                LEGACY_ACTION_FIELD: review.get("旧处置动作快照", ""),
                SOURCE_FIELD: review.get("实际确认来源快照", ""),
                "差异类型": review.get("差异类型快照", ""),
                "发生时间": "",
                "错误码": "",
                "复核状态": review.get("复核状态", ""),
                "归属值班员": review.get("归属值班员", ""),
                "领取时间": review.get("领取时间", ""),
                "复核时间": review.get("复核时间", ""),
                "复核备注": review.get("复核备注", ""),
            })
        return sorted(merged, key=lambda item: item["追踪号"])

    def _join_review(self, diff: dict[str, Any], review: dict[str, Any] | None) -> dict[str, Any]:
        row = dict(diff)
        if review is None:
            row.update({
                "复核状态": "待领取", "归属值班员": "",
                "领取时间": "", "复核时间": "", "复核备注": "",
            })
        else:
            row.update({
                "复核状态": review.get("复核状态", ""),
                "归属值班员": review.get("归属值班员", ""),
                "领取时间": review.get("领取时间", ""),
                "复核时间": review.get("复核时间", ""),
                "复核备注": review.get("复核备注", ""),
            })
        return row

    def _filter_scope(self, rows: list[dict[str, Any]], scope: str) -> list[dict[str, Any]]:
        if scope == SCOPE_ALL:
            return list(rows)
        if scope == SCOPE_UNCLAIMED:
            return [row for row in rows if row.get("复核状态") == "待领取"]
        if scope == SCOPE_CLAIMED:
            return [row for row in rows if row.get("复核状态") == "已领取"]
        if scope == SCOPE_REVIEWED:
            return [row for row in rows if row.get("复核状态") == "已复核"]
        # 默认 open：待领取 + 复核中。
        return [row for row in rows if row.get("复核状态") in ("待领取", "已领取")]

    def _find_review(self, trace_id: str) -> dict[str, Any] | None:
        for row in store.rows(REVIEW_MODULE):
            if str(row.get("追踪号", "")) == trace_id:
                return row
        return None

    def _snapshot_error_rows(self, trace_id: str) -> list[dict[str, Any]]:
        return [
            dict(row) for row in store.rows(self.MODULE)
            if str(row.get("追踪号", "")) == trace_id
        ]
