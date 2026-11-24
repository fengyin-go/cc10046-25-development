# 网络数据采集与RPA自动化平台

面向网页数据采集、自动化流程编排、解析规则管理、代理池调度与采集结果校验的数据采集工程平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8010/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5174/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8010`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 爬虫配置 | `crawler_config` | 爬虫配置 | 配置标识、起始地址、页面编码 |
| 解析规则 | `parser_rule` | 解析规则 | 规则标识、目标页面、字段选择器 |
| 代理池 | `proxy_pool` | 代理节点 | 节点标识、代理地址、代理协议 |
| Cookie管理 | `cookie_mgr` | Cookie会话 | 会话标识、来源站点、Cookie内容 |
| 限速控制 | `rate_limiter` | 限速策略 | 策略标识、目标站点、请求频率 |
| 抽取模板 | `extraction_template` | 抽取模板 | 模板标识、适用站点、列表选择器 |
| 数据校验器 | `data_validator` | 校验规则 | 规则标识、校验字段、校验类型 |
| 采集调度 | `crawl_schedule` | 调度任务 | 任务标识、关联配置、调度周期 |
| 结果存储 | `result_store` | 存储批次 | 批次标识、来源配置、采集时间 |
| 去重引擎 | `dedup_engine` | 去重策略 | 策略标识、业务键列、排序字段 |
| 字段映射 | `field_mapper` | 映射方案 | 方案标识、来源字段、目标字段 |
| 异常重试 | `error_retry` | 重试策略 | 策略标识、错误类型、重试次数 |
| 批次追踪 | `batch_tracker` | 采集批次 | 批次标识、调度任务、开始时间 |
| 导出通道 | `export_channel` | 导出任务 | 任务标识、来源批次、导出格式 |
| 采集审计 | `crawl_audit` | 审计记录 | 记录标识、操作类型、操作对象 |
| 来源认证 | `source_auth` | 认证凭证 | 凭证标识、来源站点、认证方式 |
| HTML清洗 | `html_cleaner` | 清洗模板 | 模板标识、适用站点、标签过滤 |
| 增量同步 | `incremental_sync` | 同步水位 | 水位标识、来源配置、增量字段 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 错误处置差异复核

错误记录（`error_logger`）在详情实际状态之外，还保留采集错误处理数据回传的两栏旧值
（`旧处理状态`、`旧处置动作`）和 `实际确认来源`。两栏对不上的追踪号进入错误处置差异视图：

- `GET /api/error-dispositions?scope=open|unclaimed|claimed|reviewed|all`：按追踪号列出
  详情状态、两栏旧值、实际确认来源、差异类型（状态冲突 / 旧处置缺失）与复核归属。
- `GET /api/error-dispositions/snapshot`：待复核统计与待领明细同一次实时计算，
  运营概览（`GET /api/overview` 的 `disposition` 字段）直接消费同一实际范围。
- `POST /api/error-dispositions/{追踪号}/claim`：值班员领取，进程内加锁保证并发领取
  同一追踪号只有一人成功，失败方刷新后仍能查到归属。
- `POST /api/error-dispositions/{追踪号}/review`：归属值班员复核，只写内部复核表
  （`error_disposition_review`，不出现在概览模块列表），不回写错误记录、不重新触发
  实际错误处理；已复核历史凭快照在 `all`/`reviewed` 范围持续可查。
- 错误详情页动作首次处置时把动作前状态冻结进两栏旧值，原 CSV 导出保留两栏用于对账；
  两栏重新一致后差异自动从待领列表消失（随实际结案同步）。

领域：数据工程
子方向：数据采集、爬虫与RPA
