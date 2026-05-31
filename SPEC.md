# Nexus - AI Gateway SPEC

## 1. 产品概述

| 属性 | 值 |
|------|-----|
| 产品名称 | Nexus |
| 开发公司 | 夜小白科技有限公司 |
| 产品类型 | AI Gateway Web 应用 |
| 核心功能 | 会话管理 + 记忆系统 + AI 对话 + 插件扩展 |
| 技术原则 | 基于 DeepAgents SDK，不过度封装 |

## 2. 技术架构

### 2.1 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 前端 | React + TypeScript + Vite | SPA 应用 |
| 状态管理 | Zustand | 轻量状态管理 |
| UI | Tailwind CSS | 宫崎骏森林风格主题 |
| 后端 | FastAPI | Python ASGI 框架 |
| Agent 框架 | DeepAgents 0.6+ | SDK，不过度封装 |
| LLM | MiniMax-M2.7 / DeepSeek / Qwen | OpenAI SDK 兼容 |
| 通信协议 | WebSocket | 实时流式双向通信 |
| 会话存储 | SQLite | 自建表结构 |
| 守护进程 | launchd (macOS) / systemd (Linux) | 常驻 + 开机自启 |

### 2.2 系统架构

```
┌─────────────┐         HTTP/WebSocket        ┌─────────────┐
│   React     │ ◄─────────────────────────────► │   FastAPI   │
│   Frontend  │                              │   Backend   │
│   (:30000)  │                              │   (:30000)  │
└─────────────┘                              └──────┬──────┘
                                                    │
                           ┌────────────────────────┼────────────────────────┐
                           │                        │                        │
                    ┌──────▼──────┐          ┌──────▼──────┐          ┌──────▼──────┐
                    │  Session    │          │   Memory    │          │    MCP      │
                    │  Manager    │          │   Service   │          │   Plugin    │
                    └─────────────┘          └─────────────┘          └─────────────┘
```

### 2.3 项目结构

```
nexus/
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── components/     # UI 组件
│   │   ├── store/          # Zustand 状态
│   │   ├── types/          # TypeScript 类型
│   │   ├── App.tsx         # 主应用
│   │   └── index.css       # 全局样式
│   └── public/             # 静态资源
├── nexus/
│   ├── backend/             # FastAPI 后端
│   │   ├── main.py         # 服务入口 + API + WebSocket
│   │   ├── config.py       # 配置管理
│   │   ├── agent.py        # DeepAgents 封装
│   │   ├── sessions.py     # 会话管理
│   │   ├── memory.py      # 记忆系统
│   │   ├── db.py          # SQLite 数据库
│   │   ├── channels/      # 通道实现
│   │   └── mcp.py          # MCP 插件加载
│   └── cli/                 # CLI 命令
├── tests/                   # 测试
├── docs/                    # 文档
└── pyproject.toml          # Python 包配置
```

## 3. 功能模块

### 3.1 会话管理

- 统一会话上下文管理
- 构建带记忆的 prompt
- WebSocket 实时通信
- 支持软删除和恢复
- 多通道支持（main / wechat）

### 3.2 记忆系统

- BM25 关键词检索（rank-bm25）
- SQLite LIKE 回退
- 记忆类别：preference / knowledge / context
- 自动缓存失效

### 3.3 上下文窗口

- 85% 阈值触发压缩
- 保留最近 15 条消息
- 手动触发 `/api/context/compact`

### 3.4 MCP 插件系统

- 动态加载 MCP 服务器
- 工具函数注册
- 过滤器支持

### 3.5 微信通道

- 二维码登录
- 消息回调处理
- 会话自动创建

### 3.6 前端界面

- 宫崎骏森林风格主题
- 深色/浅色模式切换
- 思考过程开关
- 实时流式响应
- Markdown 渲染

## 4. API 设计

### 4.1 REST API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/api/` | GET | API 信息 |
| `/api/sessions` | GET | 会话列表 |
| `/api/sessions` | POST | 创建会话 |
| `/api/sessions/{id}` | GET | 会话详情 |
| `/api/sessions/{id}` | PUT | 更新会话 |
| `/api/sessions/{id}` | DELETE | 软删除会话 |
| `/api/sessions/{id}/messages` | GET | 消息历史 |
| `/api/model` | GET | 当前模型信息 |
| `/api/models` | GET | 模型列表 |
| `/api/models/switch` | POST | 切换模型 |
| `/api/models` | POST | 创建模型 |
| `/api/models/{id}` | PUT | 更新模型 |
| `/api/models/{id}` | DELETE | 删除模型 |
| `/api/context` | GET | 上下文窗口信息 |
| `/api/context/compact` | POST | 触发压缩 |
| `/api/channels/wechat/bind` | GET/POST/DELETE | 微信绑定 |

### 4.2 WebSocket

- **端点**: `ws://localhost:30000/api/ws?token=<token>`
- **认证**: token query 参数

**消息类型**：

| 类型 | 说明 |
|------|------|
| `token_usage` | Token 用量 |
| `thinking` | 思考过程片段 |
| `chunk` | 响应内容片段 |
| `final` | 最终响应 |
| `done` | 完成 |
| `error` | 错误 |

## 5. 数据库设计

### 5.1 表结构

```sql
-- 会话表
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    channel TEXT DEFAULT 'main',
    deleted_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 消息表
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    thinking_content TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

-- 记忆表
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    category TEXT NOT NULL,
    memory_type TEXT DEFAULT 'explicit',
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 索引

```sql
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_sessions_updated ON sessions(updated_at);
CREATE INDEX idx_memories_session ON memories(session_id);
```

## 6. CLI 设计

### 6.1 命令

| 命令 | 说明 |
|------|------|
| `nexus install` | 注册守护进程服务 |
| `nexus start` | 启动服务 |
| `nexus stop` | 停止服务 |
| `nexus restart` | 重启服务 |
| `nexus status` | 查看状态 |
| `nexus logs` | 查看日志 |
| `nexus uninstall` | 移除服务注册 |
| `nexus setup` | 交互式配置向导 |
| `nexus doctor` | 环境诊断 |

### 6.2 进程信息

| 项目 | 值 |
|------|-----|
| 进程名 | `nexus-gateway` |
| 端口 | 30000 |
| 日志 | `~/.nexus/logs/` |
| 数据 | `~/.nexus/nexus.db` |

## 7. 部署

### 7.1 pip 安装

```bash
pip install nexus
nexus install
nexus start
```

### 7.2 源码安装

```bash
git clone https://github.com/your-org/nexus.git
cd nexus
pip install -e .
nexus install
nexus start
```

### 7.3 开发模式

```bash
# 后端
python -m nexus.backend.run

# 前端
cd frontend && npm run dev
```

## 8. 版本状态

### 已完成

- [x] FastAPI 服务入口
- [x] WebSocket 实时通信
- [x] DeepAgents 集成
- [x] SQLite 会话管理
- [x] MemoryService (BM25)
- [x] CLI 命令（install/start/stop/status/logs）
- [x] launchd 守护进程
- [x] 开机自启
- [x] 前端界面（森林风格主题）
- [x] 思考过程开关
- [x] 多模型支持
- [x] 微信通道集成

### 进行中

- [ ] MCP 插件市场
- [ ] 文档完善

---

*最后更新: 2026-06-01*
*作者: 夜小白科技有限公司*