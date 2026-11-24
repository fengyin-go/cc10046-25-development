"""错误处置差异视图路由：差异明细、领取、复核与复核口径快照。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import ActionResult, ClaimPayload, PageResult, ReviewPayload
from app.services.error_logger import SCOPE_ALL, SCOPE_OPEN, ErrorLoggerService

router = APIRouter(prefix="/api/error-dispositions", tags=["错误处置差异"])

_service = ErrorLoggerService()


@router.get("", response_model=PageResult[dict])
def list_dispositions(
    scope: str = Query(default=SCOPE_OPEN),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=200),
) -> PageResult[dict]:
    """按追踪号列出两栏对不上的错误，scope 控制待领/复核中/已复核/全部范围。"""
    items, total = _service.list_dispositions(
        scope=scope, keyword=keyword, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/snapshot")
def disposition_snapshot() -> dict:
    """运营概览复核明细：待复核统计与待领列表同一实际范围、同一次实时计算。"""
    return _service.disposition_snapshot()


@router.post("/{trace_id}/claim", response_model=ActionResult)
def claim_disposition(trace_id: str, payload: ClaimPayload) -> ActionResult:
    """值班员按追踪号领取差异；并发领取同一追踪号只有一人成功。"""
    entry, message = _service.claim_disposition(trace_id, payload.operator)
    return ActionResult(ok=entry is not None, message=message, entry=entry)


@router.post("/{trace_id}/review", response_model=ActionResult)
def review_disposition(trace_id: str, payload: ReviewPayload) -> ActionResult:
    """归属值班员完成复核；只更新复核状态，不重新触发实际错误处理。"""
    entry, message = _service.review_disposition(trace_id, payload.operator, payload.remark or "")
    return ActionResult(ok=entry is not None, message=message, entry=entry)
