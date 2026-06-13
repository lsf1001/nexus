# Nexus

夜小白科技有限公司开发的 AI Gateway（智能对话 / 会话管理 / 记忆系统 / MCP 插件 / 微信通道）。

> **回复语言**：简体中文。
>
> **硬性约束**：见 `@python_project.md`（违规 CI 阻断）。

@python_project.md

## 项目信息

- 名称：Nexus
- 用途：AI Gateway，三进程/三目录独立构建
- 技术栈：React 19 + FastAPI + DeepAgents + WebSocket + SQLite + Electron
- 三进程：Python 后端（端口 30000）、React 前端（端口 30077）、Electron 桌面端（macOS DMG）
- Python 强制使用 `.venv`，不允许系统 Python

## 架构

- `nexus/backend/`：FastAPI 后端（端口 30000）— `main.py` 入口、`agent.py` DeepAgents 封装、`db.py` SQLite + 自动迁移
- `nexus/cli/`：Typer CLI（install/start/stop/doctor/daemon）
- `frontend/`：Vite + React（端口 30077）— `src/components/` `src/hooks/` `e2e/`
- `desktop/`：Electron + electron-builder — `src/{main,backend,preload}.ts`
- `tests/`：pytest 后端测试
- `docs/superpowers/`：设计稿 / 计划 / 进度
- `docs/operations/`：运维文档（含 quality.md 质量门）

## 命令

仓库根 `/Users/yxb/projects/nexus/`。

```bash
# 后端（首次）
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# CLI 服务管理
nexus install|start|stop|restart|status|logs|doctor|uninstall

# 后端开发与测试
source .venv/bin/activate
pytest tests/                          # 全量
pytest tests/test_xxx.py::TestMethod   # 单方法
ruff check nexus/                      # lint
ruff format nexus/                     # 格式化

# 前端
cd frontend && npm install
npm run dev|build|lint|test:e2e

# 桌面端
cd desktop && npm install
npm run dev|test|pack

# 顶层 npm 脚本
npm run desktop:install|build|dev|test|pack
```

## 关键约束

<立项时从 SPEC 摘录 3-5 条最硬约束>

- **WebSocket 协议** `/api/ws`，流式响应：`thinking` → `chunk` → `final` → `done`，支持多客户端
- **WS 跨线程桥接**：流式回调在子线程中用 `asyncio.run_coroutine_threadsafe` 投递回事件循环，**禁止**在子线程直接 `await`
- **DB PRAGMA**：`db.py` 在连接建立时启用 `foreign_keys=ON / journal_mode=WAL / synchronous=NORMAL`；缺列自动 `ALTER TABLE ADD COLUMN`（无需手工迁移脚本）
- **`models.json` 写入必须走 `models_config.save_models()`**，**不要**绕过原子写流程
- 测试覆盖三类：正常路径 / 边界条件 / 异常路径

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MINIMAX_API_KEY` / `MINIMAX_API_BASE` | — | 首选（兼容 `MINIMAX_API_KEY` / `MiniMax_API_KEY`） |
| `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL` | — | Anthropic 风格兼容 |
| `NEXUS_WS_TOKEN` | `nexus-default-token` | WebSocket 认证 |
| `NEXUS_PORT` | `30000` | 后端端口 |
| `NEXUS_ENABLE_MCP` | `true` | 启用 MCP |
| `NEXUS_ALLOWED_ORIGINS` | `*` (dev) | CORS 白名单，逗号分隔 |

API Key 解析顺序：`MINIMAX_API_KEY` → `MiniMax_API_KEY` → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY`，**首次匹配胜出**。

运行时配置目录：`~/.nexus/`（`models.json` / `nexus.db` / `logs/`）。

## 数据库（SQLite 单文件）

`sessions` / `messages` / `memory` / `tool_stats` / `session_stats`。

- `memory` 表单数（不是 `memories`），包含 `category` / `memory_type` / `is_active` 字段，由 `EvolutionService` 维护
- **任何 schema 改动优先走 `db.py` 的 `_ensure_column()` 自动迁移**，**禁止**直接写 `ALTER TABLE`

## 文档导航

- [`README.md`](./README.md) — 安装、CLI、API 速查、服务端口
- [`SPEC.md`](./SPEC.md) — 完整技术规格（架构图、模块职责、DB schema、稳定性修复清单）
- [`python_project.md`](./python_project.md) — Python 工程规约（硬性约束）
- [`CHANGELOG.md`](./CHANGELOG.md) — 版本变更
- [`docs/superpowers/`](./docs/superpowers/) — 设计稿 / 计划 / 进度
- [`docs/operations/quality.md`](./docs/operations/quality.md) — 质量门
