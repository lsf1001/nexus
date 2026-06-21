# Nexus - AI Gateway

Nexus 是夜小白科技有限公司开发的 AI Gateway，支持智能对话、会话管理、记忆系统和 MCP 插件扩展。

## 快速开始

```bash
# 一键安装
curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/install.sh | bash

# 启动服务
nexus start
```

访问 http://localhost:30077/

## 功能

- **智能对话** - MiniMax / DeepSeek / Qwen 多模型支持
- **会话管理** - 支持软删除和恢复
- **记忆系统** - BM25 关键词检索
- **上下文压缩** - 85% 阈值自动触发
- **WebSocket** - 实时流式响应
- **微信通道** - 二维码登录集成
- **MCP 插件** - 动态加载扩展

## 安装

### 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/lsf1001/nexus/main/install.sh | bash
```

### 源码安装

```bash
git clone https://github.com/lsf1001/nexus.git ~/.nexus
cd ~/.nexus
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
nexus install && nexus start
```

> **交付包说明**：仓库不包含 `node_modules/`、`frontend/dist/`、`.venv/`、构建产物（`dist/*.whl` / `dist/*.tar.gz`）与 `__pycache__/` 等运行时缓存。
> 首次拉取后请先执行：
> ```bash
> # 后端依赖
> python3 -m venv .venv && source .venv/bin/activate
> pip install -e .
> # 前端依赖（如需本地构建）
> cd frontend && npm install
> ```

### pip 安装（待 PyPI 发布）

```bash
pip install nexus && nexus install && nexus start
```

## CLI

```bash
nexus install    # 注册服务（开机自启）
nexus start      # 启动
nexus stop       # 停止
nexus restart    # 重启
nexus status     # 状态
nexus logs       # 日志
nexus uninstall  # 卸载
nexus doctor     # 诊断
```

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

---

夜小白科技有限公司