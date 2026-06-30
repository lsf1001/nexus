# Nexus - AI Gateway

Nexus 是夜小白科技有限公司开发的 AI Gateway，支持智能对话、会话管理、记忆系统和 MCP 插件扩展。

## 快速开始

**终端用户**：下载 `Nexus.dmg` 拖到 `/Applications/`，双击 `Nexus.app` 启动。数据全部在 `~/.nexus/`。

**开发者**：从 git clone 跑起来：

```bash
git clone https://github.com/lsf1001/nexus.git
cd nexus
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
(cd frontend && npm install)

# 起后端（一个 terminal）
python nexus/backend/run.py    # 监听 30000

# 起前端（另一个 terminal）
(cd frontend && npm run dev)   # 监听 30077
```

浏览器开 http://localhost:30077/ 。配置 API Key 见下方 [配置](#配置)。

> **macOS DMG 用户**：v0.1.0 release 暂未挂 DMG 安装包（网络上传限制），可在本地构建：`cd desktop && npm install && npm run pack`，产物在 `desktop/dist/`。详见下方 [macOS 桌面端（DMG）](#macos-桌面端dmg)。

## 功能

- **智能对话** - MiniMax / DeepSeek / Qwen 多模型支持
- **会话管理** - 支持软删除和恢复
- **记忆系统** - deepagents `MemoryMiddleware` 自动加载 `AGENTS.md`（用户级 `~/.nexus/AGENTS.md` + 项目级 `nexus/.deepagents/AGENTS.md`），LLM 通过内置 `edit_file` 自更新；`QualityGateMiddleware` 拦截写入做忠实度评分
- **上下文压缩** - 85% 阈值自动触发
- **WebSocket** - 实时流式响应
- **微信通道** - 二维码登录集成
- **MCP 插件** - 动态加载扩展
- **质量门** - 4 维度 rubric judge（safety / accuracy / completeness / tool_correctness），REPAIR/REJECT 自动降级
- **macOS 桌面端** - Tauri 2 打包的 `.dmg`(Rust 主进程 + Python sidecar),双击安装即用

## 安装

终端用户走 DMG,开发者从源码直跑,**两条路径完全独立**:

### 终端用户（macOS DMG）

下载 `Nexus.dmg` 拖到 `/Applications/`,双击 `Nexus.app` 启动。数据全部在 `~/.nexus/`。

### 开发者（git clone 直跑）

```bash
git clone https://github.com/lsf1001/nexus.git
cd nexus

# 后端
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 前端
(cd frontend && npm install)

# 起后端（一个 terminal,30000 端口）
python nexus/backend/run.py

# 起前端（另一个 terminal,30077 端口）
(cd frontend && npm run dev)
```

浏览器开 http://localhost:30077/。配置 API Key 见 [配置](#配置)。

> 仓库不包含 `node_modules/`、`frontend/dist/`、`.venv/`、构建产物（`dist/*.whl` / `dist/*.tar.gz`）与 `__pycache__/` 等运行时缓存。首次拉取后请按上面命令装依赖。

### macOS 桌面端（DMG）本地构建

> 终端用户也可本地构建 DMG（v0.1.0 release 暂未挂预构建 DMG,网络上传限制）。

```bash
bash scripts/build_dmg.sh
# 产物：release/Nexus-1.0.0-arm64.dmg（约 70 MB，arm64，未签名）
```

| 项 | 值 |
| --- | --- |
| 产物 | `release/Nexus-1.0.0-arm64.dmg`（本地构建约 70 MB，arm64） |
| 架构 | macOS Apple Silicon（Intel 暂未出包） |
| 签名 | **未签名**（内测版，无 Apple Developer ID） |
| 端口 | 后端 30000 + WKWebView 弹原生窗口（启动时自动拉起） |
| 内部结构 | `MacOS/Nexus`(壳脚本)→ exec `Resources/nexus-backend/nexus-runtime`(Python sidecar 二进制,绑定 127.0.0.1:30000) + 内嵌 WKWebView 加载 `Resources/frontend/`,由 `desktop/src-tauri/src/runtime.rs` supervisor 管理 sidecar 生命周期 |

> **首次启动绕过 Gatekeeper**（仅一次）：
>
> 1. Finder → Applications → 右键 `Nexus.app` → 打开
> 2. 弹出确认框 → 点「打开」
> 3. 之后双击即可正常启动
>
> **命令行方式**（等价）：
> ```bash
> xattr -dr com.apple.quarantine /Applications/Nexus.app
> ```

## API

| 接口                   | 方法        | 说明   |
| -------------------- | --------- | ---- |
| `/health`            | GET       | 健康检查 |
| `/api/sessions`      | GET/POST  | 会话   |
| `/api/model`         | GET       | 当前模型 |
| `/api/models`        | GET/POST  | 模型列表 |
| `/api/models/switch` | POST      | 切换模型 |
| `/api/ws`            | WebSocket | 实时对话 |

### WebSocket 示例

```javascript
const ws = new WebSocket('ws://localhost:30000/api/ws?token=nexus-default-token');
ws.send(JSON.stringify({ content: '你好' }));
// 接收: thinking → chunk → final → done
```

## 配置

环境变量（按优先级匹配）：

- `MINIMAX_API_KEY` / `MINIMAX_API_BASE`（首选）
- `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_BASE_URL`（兼容 Anthropic 风格）
- `NEXUS_WS_TOKEN`（默认 `nexus-default-token`，后端 WebSocket 鉴权）
- `VITE_NEXUS_WS_TOKEN`（前端编译期 env，Vite 只暴露 `VITE_*` 给客户端；**必须**与 `NEXUS_WS_TOKEN` 一致，否则 WS 鉴权失败）
- `NEXUS_PORT`（默认 `30000`）
- `NEXUS_ALLOWED_ORIGINS`（CORS 白名单，逗号分隔；dev 默认通配）

配置目录：`~/.nexus/`

- `models.json` - 模型配置
- `nexus.db` - 数据存储
- `logs/` - 日志文件

## 服务

| 项目  | 值                |
| --- | ---------------- |
| 后端端口 | 30000            |
| 前端端口 | 30077            |
| 进程名 | nexus-gateway    |
| 前端  | http://localhost:30077/ |

## 文档

- [SPEC.md](./SPEC.md) - 技术规格
- [CLAUDE.md](./CLAUDE.md) - 开发规范
- [CHANGELOG.md](./CHANGELOG.md) - 版本变更
- [docs/RELEASE_NOTES_v0.1.0.md](./docs/RELEASE_NOTES_v0.1.0.md) - v0.1.0 发布说明
- [scripts/build_dmg.sh](./scripts/build_dmg.sh) - DMG 打包脚本(Tauri 2 + hdiutil)
- [docs/architecture.md](./docs/architecture.md) - 产品模块图 + 逻辑架构图
- [docs/data-flow/](./docs/data-flow/) - 三条核心数据流时序图(WS / 微信 / 记忆)

---

夜小白科技有限公司