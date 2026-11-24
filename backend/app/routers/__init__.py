"""业务路由汇总：所有模块共用一套资源路由，由领域服务完成分派。"""
from __future__ import annotations

from app.routers import resource
from app.routers import chains
from app.routers import disposition

# disposition 提供 /api/error-dispositions 固定路径，必须排在通配的资源路由之前，
# 否则 /api/{module} 会先把它当成模块名匹配。
ROUTERS = [disposition, resource, chains]
