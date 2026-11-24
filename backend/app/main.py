"""网络数据采集与RPA自动化平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8010
健康检查：GET /api/health
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.services.error_logger import ErrorLoggerService
from app.store import store

app = FastAPI(title="网络数据采集与RPA自动化平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_error_logger = ErrorLoggerService()


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。

    错误处置差异的待复核统计与可领取明细来自同一次实时计算（同一实际范围），
    值班员可直接在概览按追踪号领取。
    """
    payload = store.overview()
    payload["disposition"] = _error_logger.disposition_snapshot()
    return payload


# 资源路由含 /api/{module}，必须放在 health / overview 之后注册，
# 否则固定路径会被动态路径抢先匹配。
for module in ROUTERS:
    app.include_router(module.router)
