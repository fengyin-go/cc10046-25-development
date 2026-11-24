"""错误处置差异视图：差异计算、领取并发控制、复核隔离、概览同口径与 CSV 对账测试。"""
import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from app.main import app
from app.services.error_logger import (
    LEGACY_ACTION_FIELD,
    LEGACY_STATUS_FIELD,
    REVIEW_MODULE,
    ErrorLoggerService,
)
from app.store import store

client = TestClient(app)


def _log_two_errors(tag: str) -> tuple[str, str, int, int]:
    """通过可靠性检查链路录入两条错误，返回（甲追踪号, 乙追踪号, 甲id, 乙id）。"""
    for who in ("jia", "yi"):
        client.post("/api/chains/reliability", json={"site": f"{tag}-{who}.com"})
    items = client.get("/api/error_logger", params={"size": 200}).json()["items"]
    jia = [e for e in items if e["来源模块"] == f"{tag}-jia.com"][-1]
    yi = [e for e in items if e["来源模块"] == f"{tag}-yi.com"][-1]
    return jia["追踪号"], yi["追踪号"], jia["id"], yi["id"]


def _diff_map(scope: str = "all") -> dict:
    items = client.get("/api/error-dispositions",
                       params={"scope": scope, "size": 200}).json()["items"]
    return {row["追踪号"]: row for row in items}


class TestDispositionDiff:
    def test_new_errors_are_missing_legacy_diffs(self):
        jia, yi, _, _ = _log_two_errors("case-missing")
        rows = _diff_map()
        assert jia in rows and yi in rows
        assert rows[jia]["差异类型"] == "旧处置缺失"
        assert rows[jia]["复核状态"] == "待领取"
        # 视图必须同时展示详情状态、两栏旧值与实际确认来源。
        assert rows[jia]["详情状态"] == "未处理"
        assert rows[jia][LEGACY_STATUS_FIELD] == ""
        assert rows[jia]["实际确认来源"] == "可靠性检查录入"

    def test_resolve_creates_conflict_and_freezes_legacy(self):
        jia, _, jia_id, _ = _log_two_errors("case-conflict")
        result = client.post(f"/api/error_logger/{jia_id}/actions", json={"action": "标记解决"})
        assert result.json()["ok"] is True
        row = _diff_map()[jia]
        # 甲详情已解决，旧列冻结为动作前的未处理，两栏对不上。
        assert row["详情状态"] == "已解决"
        assert row["旧处理状态"] == "未处理"
        assert row["旧处置动作"] == "标记解决"
        assert row["差异类型"] == "状态冲突"

    def test_reconciled_diff_leaves_live_view(self):
        jia, _, jia_id, _ = _log_two_errors("case-align")
        client.post(f"/api/error_logger/{jia_id}/actions", json={"action": "标记解决"})
        assert jia in _diff_map()
        # 模拟旧处理数据补传后两栏重新一致：差异自动从实时视图消失。
        entry = store.find("error_logger", jia_id)
        entry[LEGACY_STATUS_FIELD] = "已解决"
        assert jia not in _diff_map()

    def test_keyword_filter_by_trace(self):
        jia, _, _, _ = _log_two_errors("case-keyword")
        page = client.get("/api/error-dispositions",
                          params={"scope": "all", "keyword": jia}).json()
        assert page["total"] == 1
        assert page["items"][0]["追踪号"] == jia


class TestClaimAndReview:
    def test_claim_and_detail_ownership(self):
        jia, _, jia_id, _ = _log_two_errors("case-claim")
        resp = client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "值班员A"})
        assert resp.json()["ok"] is True
        assert resp.json()["entry"]["归属值班员"] == "值班员A"
        detail = client.get(f"/api/error_logger/{jia_id}").json()
        assert detail["归属值班员"] == "值班员A"
        assert detail["复核状态"] == "已领取"
        claimed = _diff_map("claimed")
        assert jia in claimed

    def test_concurrent_claim_only_one_wins(self):
        jia, _, _, _ = _log_two_errors("case-concurrent")
        outcomes: list[bool] = []
        barrier = threading.Barrier(2)
        svc = ErrorLoggerService()

        def claim(operator: str) -> None:
            barrier.wait()
            _, _ = svc.claim_disposition(jia, operator)
            review = svc._find_review(jia)
            outcomes.append(review is not None and review["归属值班员"] == operator)

        t1 = threading.Thread(target=claim, args=("值班员A",))
        t2 = threading.Thread(target=claim, args=("值班员B",))
        t1.start(); t2.start(); t1.join(); t2.join()
        assert sorted(outcomes) == [False, True]
        # 失败方刷新后仍能查到归属。
        row = _diff_map("claimed")[jia]
        assert row["归属值班员"] in ("值班员A", "值班员B")

    def test_duplicate_claim_and_unknown_trace_rejected(self):
        jia, _, _, _ = _log_two_errors("case-dup")
        client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "值班员A"})
        again = client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "值班员B"})
        assert again.json()["ok"] is False
        assert "已由 值班员A 领取" in again.json()["message"]
        bad = client.post("/api/error-dispositions/NO-SUCH-TRACE/claim", json={"operator": "值班员A"})
        assert bad.json()["ok"] is False
        empty = client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "  "})
        assert empty.json()["ok"] is False

    def test_review_does_not_touch_error_record(self):
        jia, _, jia_id, _ = _log_two_errors("case-review")
        client.post(f"/api/error_logger/{jia_id}/actions", json={"action": "标记解决"})
        client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "值班员A"})
        before = dict(client.get(f"/api/error_logger/{jia_id}").json())
        # 非归属人不能复核。
        forbidden = client.post(f"/api/error-dispositions/{jia}/review",
                                json={"operator": "值班员C"})
        assert forbidden.json()["ok"] is False
        ok = client.post(f"/api/error-dispositions/{jia}/review",
                         json={"operator": "值班员A", "remark": "以详情为准"})
        assert ok.json()["ok"] is True
        after = client.get(f"/api/error_logger/{jia_id}").json()
        for field in ("status", "处理状态", LEGACY_STATUS_FIELD, LEGACY_ACTION_FIELD,
                      "实际确认来源", "发生时间"):
            assert before[field] == after[field]
        # 复核后离开待复核范围，但历史仍可查。
        assert jia not in _diff_map("open")
        history = _diff_map("reviewed")
        assert jia in history
        assert history[jia]["复核备注"] == "以详情为准"
        # 已复核不能重复领取或复核。
        assert client.post(f"/api/error-dispositions/{jia}/claim",
                           json={"operator": "值班员B"}).json()["ok"] is False
        assert client.post(f"/api/error-dispositions/{jia}/review",
                           json={"operator": "值班员A"}).json()["ok"] is False


class TestOverviewAndExport:
    def test_overview_snapshot_same_scope_as_list(self):
        jia, yi, _, _ = _log_two_errors("case-overview")
        overview = client.get("/api/overview").json()
        snap = overview["disposition"]
        open_total = client.get("/api/error-dispositions",
                                params={"scope": "open"}).json()["total"]
        unclaimed_total = client.get("/api/error-dispositions",
                                     params={"scope": "unclaimed"}).json()["total"]
        assert snap["待复核"] == open_total
        assert snap["待领取"] == unclaimed_total
        assert len(snap["open_items"]) == snap["待领取"]
        traces = {item["追踪号"] for item in snap["open_items"]}
        assert {jia, yi} <= traces
        # 内部复核表不作为业务模块出现在概览。
        names = [m["name"] for m in overview["modules"]]
        assert REVIEW_MODULE not in names
        assert "error_logger" in names

    def test_claim_from_overview_updates_both_stats_and_list(self):
        jia, _, _, _ = _log_two_errors("case-overview-claim")
        before = client.get("/api/overview").json()["disposition"]["待领取"]
        client.post(f"/api/error-dispositions/{jia}/claim", json={"operator": "值班员A"})
        after = client.get("/api/overview").json()["disposition"]
        assert after["待领取"] == before - 1
        open_traces = {item["追踪号"] for item in after["open_items"]}
        assert jia not in open_traces

    def test_csv_export_keeps_legacy_columns(self):
        jia, _, jia_id, _ = _log_two_errors("case-csv")
        client.post(f"/api/error_logger/{jia_id}/actions", json={"action": "标记解决"})
        text = client.get("/api/error_logger/export").text
        header = text.splitlines()[0]
        assert "旧处理状态" in header and "旧处置动作" in header
        jia_lines = [line for line in text.splitlines() if jia in line]
        assert jia_lines and "未处理" in jia_lines[0] and "标记解决" in jia_lines[0]
