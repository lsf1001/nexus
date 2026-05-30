# Nexus PRD - AI Gateway

## 1. 产品概述

| 属性 | 值 |
|------|-----|
| 产品名称 | Nexus |
| 开发公司 | 夜小白科技有限公司 |
| 产品类型 | AI Gateway Web 应用 |
| 核心功能 | 会话管理 + 记忆系统 + AI 对话 + 插件扩展 |
| 技术原则 | 基于 DeepAgents SDK，参考 OpenClaw/Hermes 设计 |

## 2. 技术架构

### 2.1 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 前端 | React + Vite | SPA 应用 |
| 后端 | FastAPI | Python ASGI 框架 |
| Agent 框架 | DeepAgents 0.6.4 | SDK，不过度封装 |
| LLM | MiniMax-M2.7 | OpenAI SDK 兼容 |
| 通信协议 | WebSocket | 实时流式双向通信 |
| 会话存储 | SQLite | 自建表结构 |
| 守护进程 | launchd (macOS) / systemd (Linux) | 常驻 + 开机自启 |

### 2.2 系统架构图

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
                    │  (会话管理)   │          │  (BM25检索)  │          │   System    │
                    └─────────────┘          └─────────────┘          └─────────────┘
                           │
                    ┌──────▼──────┐
                    │  SQLite     │
                    │  (会话+记忆) │
                    └─────────────┘
```

### 2.3 项目结构

```
nexus/
├── frontend/                 # React 前端
│   ├── src/
│   │   ├── components/     # UI 组件
│   │   ├── store/          # Zustand 状态
│   │   └── App.tsx         # 主应用
│   └── public/             # 静态资源
├── nexus/
│   ├── backend/             # FastAPI 后端
│   │   ├── main.py         # 服务入口 + WebSocket
│   │   ├── config.py       # 配置管理
│   │   ├── agent.py        # DeepAgents 封装
│   │   ├── sessions.py     # 会话管理（SessionManager）
│   │   ├── memory.py        # 记忆系统（BM25 + SQLite）
│   │   ├── db.py           # SQLite 数据库
│   │   ├── run.py          # 启动脚本（CLI 兼容）
│   │   └── requirements.txt
│   └── cli/                 # CLI 命令
│       ├── main.py         # CLI 入口
│       ├── daemon/         # 守护进程管理
│       └── ...
├── CLAUDE.md               # 开发规范
├── README.md               # 用户文档
└── docker-compose.yml      # Docker 备用部署
```

## 3. 功能模块

### 3.1 会话管理 (SessionManager)

- 统一会话上下文管理
- 构建带记忆的 prompt
- WebSocket 实时通信
- 线程安全单例模式

### 3.2 记忆系统 (MemoryService)

- BM25 关键词检索（rank-bm25 库）
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
| `/api/sessions/{id}/restore` | POST | 恢复会话 |
| `/api/sessions/{id}/permanent` | DELETE | 永久删除 |
| `/api/sessions/{id}/messages` | GET | 消息历史 |
| `/api/sessions/{id}/messages` | POST | 添加消息 |
| `/api/sessions/{id}/history` | GET | AI 用历史 |
| `/api/model` | GET | 当前模型 |
| `/api/models` | GET | 模型列表 |
| `/api/models/switch` | POST | 切换模型 |
| `/api/models` | POST | 创建模型 |
| `/api/models/{id}` | PUT | 更新模型 |
| `/api/models/{id}` | DELETE | 删除模型 |
| `/api/context` | GET | 上下文信息 |
| `/api/context/compact` | POST | 触发压缩 |

### 4.2 WebSocket

- **端点**: `ws://localhost:30000/api/ws?token=xxx`
- **认证**: token 参数

### 4.3 微信通道 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/channels/wechat/qr` | POST | 获取二维码 |
| `/api/channels/wechat/status/{key}` | GET | 二维码状态 |
| `/api/channels/wechat/bind` | GET | 绑定状态 |
| `/api/channels/wechat/bind` | POST | 绑定账号 |
| `/api/channels/wechat/bind` | DELETE | 解绑 |

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

-- 模型配置表
CREATE TABLE models (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    api_key TEXT,
    api_base TEXT,
    temperature REAL DEFAULT 0.7,
    is_active INTEGER DEFAULT 0,
    max_context_tokens INTEGER DEFAULT 200000,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 索引

```sql
CREATE INDEX idx_messages_session ON messages(session_id);
CREATE INDEX idx_sessions_updated ON sessions(updated_at);
CREATE INDEX idx_memories_session ON memories(session_id);
CREATE INDEX idx_memories_key ON memories(key);
```

## 6. CLI 设计

### 6.1 命令

```bash
nexus install    # 注册 launchd 服务
nexus start      # 启动服务
nexus stop       # 停止服务
nexus restart    # 重启服务
nexus status     # 查看状态
nexus logs       # 查看日志
nexus uninstall  # 移除服务
nexus setup      # 交互式配置
nexus doctor     # 环境诊断
nexus gateway    # 网关子命令（向后兼容）
nexus config     # 配置管理
```

### 6.2 launchd plist

```xml
<key>Label</key>
<string>ai.nexus.gateway</string>
<key>RunAtLoad</key>
<true/>
<key>KeepAlive</key>
<true/>
```

## 7. 部署方式

### 7.1 对比 OpenClaw / Hermes

| 项目 | Claude Code | OpenClaw | Hermes | Nexus |
|------|-------------|----------|--------|-------|
| 安装 | `brew install` | `npm install -g` | `pip install` | `pip install nexus` |
| 部署 | App Bundle | npm 全局 | venv + pip | .venv + pip |
| 守护 | 内置 | launchd | launchd | launchd |
| 自启 | macOS 系统 | RunAtLoad | RunAtLoad | RunAtLoad |
| 管理 | GUI | CLI | CLI | CLI |

### 7.2 安装流程

```bash
# 1. 安装
pip3 install nexus

# 2. 配置 launchd
nexus install

# 3. 启动
nexus start
```

### 7.3 服务信息

| 项目 | 值 |
|------|-----|
| 进程名 | ai.nexus.gateway |
| 端口 | 30000 |
| 日志 | ~/.nexus/logs/stdout.log, stderr.log |
| 数据 | ~/.nexus/nexus.db |
| PID | ~/.nexus/run/nexus.pid |

## 8. 开发计划

### Phase 1: 核心功能 ✓

- [x] FastAPI 服务入口
- [x] WebSocket 端点
- [x] DeepAgents 集成
- [x] SQLite 会话管理
- [x] SessionManager
- [x] MemoryService (BM25)

### Phase 2: CLI 和部署 ✓

- [x] CLI 命令（install/start/stop/status/logs）
- [x] launchd 守护
- [x] 开机自启

### Phase 3: 完善功能

- [ ] 前端界面优化
- [ ] 微信通道完整功能
- [ ] MCP 插件市场

---

*最后更新: 2026-05-30*
*作者: 夜小白科技有限公司*