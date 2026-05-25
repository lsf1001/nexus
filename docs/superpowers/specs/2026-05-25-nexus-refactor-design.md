# Nexus 重构设计方案

**日期**: 2026-05-25
**目标**: 全面迁移到 DeepAgents 原生架构

---

## 1. 背景与目标

当前项目基于 DeepAgents SDK 开发，但只使用了最小化的 `create_deep_agent(tools=)` 配置，缺失了框架自带的多个核心能力：Memory、Skills、Summarization、StoreBackend 等。同时手动实现了 SQLite session 管理，与框架设计不兼容。

本次重构目标：

- 启用完整的 DeepAgents middleware 架构
- 用 StoreBackend 替代手写的 SQLite session 管理
- 前端简化为纯 UI，session 由 DeepAgents 处理
- 整合 SOUL.md 到 Memory 系统

---

## 2. 架构变化

### 当前架构

```
前端 → WebSocket → FastAPI → agent.py → SQLite (session.py)
                                    ↓
                              SOUL.md (静态)
```

### 目标架构

```
前端 → WebSocket → FastAPI → DeepAgents (StoreBackend)
                              ↓
                         MemoryMiddleware
                         SkillsMiddleware
                         SummarizationMiddleware
                         FilesystemMiddleware
                              ↓
                         langgraph.store (原生持久化)
```

---

## 3. 后端改动

### 3.1 新目录结构

```
nexus/
├── .deepagents/
│   ├── AGENTS.md          # 记忆系统（整合原 SOUL.md）
│   └── skills/            # 技能定义目录
│       └── README.md      # 技能说明
└── backend/
    ├── __init__.py
    ├── agent.py           # 重写：添加 backend + middleware
    ├── main.py            # 简化：移除 session 逻辑
    ├── config.py          # 保留
    └── tools.py           # 保留
```

### 3.2 agent.py 重写

```python
from deepagents import create_deep_agent
from deepagents.backends.langgraph import StoreBackend
from deepagents import MemoryMiddleware, SkillsMiddleware
from deepagents.middleware.subagents import SubAgentMiddleware, SubAgent

def create_agent() -> Any:
    from .tools import TOOLS

    backend = StoreBackend()

    return create_deep_agent(
        model=get_llm(),
        tools=TOOLS,
        system_prompt=get_system_prompt(),
        backend=backend,
        memory=[
            "~/.deepagents/AGENTS.md",
            str(Path(__file__).parent.parent / ".deepagents" / "AGENTS.md"),
        ],
        skills=[
            "~/.deepagents/skills/",
            str(Path(__file__).parent.parent / ".deepagents" / "skills"),
        ],
    )
```

### 3.3 移除的模块

- `session.py` - DeepAgents StoreBackend 替代
- `database.py` - StoreBackend 替代

### 3.4 main.py 简化

- 移除 `create_session`、`get_conversation_history` 等 session 函数
- WebSocket 端点简化为只做消息转发
- session 生命周期由 DeepAgents 管理

---

## 4. 前端改动

### 4.1 移除的状态管理

- `sessions: Session[]` - 删除
- `currentSessionId: string | null` - 删除
- `messages: Record<string, Message[]>` - 删除
- `addSession`, `setCurrentSession`, `addMessage`, `truncateMessages` - 删除

### 4.2 保留的状态管理

```typescript
interface AppState {
  input: string;
  isLoading: boolean;
  wsConnected: boolean;
  showThinking: boolean;
  wsError: string | null;
}
```

### 4.3 简化后的 ChatArea

- 连接 DeepAgents WebSocket
- 发送消息 / 接收流式响应
- 不再管理 session 生命周期
- UI 只负责渲染和用户交互

---

## 5. Memory 系统设计

### 5.1 AGENTS.md 内容

整合原 SOUL.md 到 Memory 系统：

```markdown
# Nexus 身份

你是 **Nexus**，夜小白科技有限公司开发的 AI 助手。

## 基本信息
- 名字: Nexus
- 开发者: 夜小白科技有限公司
- 底层模型: MiniMax-M2.7

## 回答规则
1. 直接回答，不要过度铺垫
2. 使用思考标签 <thinking></thinking>
3. 用中文回答

<!-- 此文件由 DeepAgents MemoryMiddleware 自动管理 -->
<!-- AI 会根据对话自动更新记忆 -->
```

### 5.2 记忆更新机制

DeepAgents MemoryMiddleware 会根据对话自动：

- 学习用户偏好
- 记录重要上下文
- 更新 AGENTS.md 文件

---

## 6. Skills 系统设计

### 6.1 目录结构

```
.deepagents/skills/
└── README.md
```

### 6.2 Skills 说明

Skills 系统支持渐进式技能披露，当任务需要时自动加载对应技能。

---

## 7. Middleware 完整配置

| Middleware              | 参数                     | 作用         |
| ----------------------- | ---------------------- | ---------- |
| TodoListMiddleware      | 默认启用                   | 任务列表管理     |
| FilesystemMiddleware    | backend                | 文件操作工具     |
| SubAgentMiddleware      | subagents=[]           | 子代理能力      |
| SummarizationMiddleware | 自动                     | token 截断压缩 |
| MemoryMiddleware        | memory=["AGENTS.md路径"] | 记忆系统       |
| SkillsMiddleware        | skills=["skills路径"]    | 技能系统       |

---

## 8. 数据迁移

**旧 SQLite 数据处理**: 丢弃，不迁移。

原因：

- 重构本身就是全新开始
- 历史会话价值有限
- 避免迁移复杂度和风险

---

## 9. 实施步骤

### Phase 1: 后端重构

1. 创建 `.deepagents/AGENTS.md`（整合 SOUL.md）
2. 创建 `.deepagents/skills/` 目录
3. 重写 `agent.py`，添加 backend + middleware
4. 简化 `main.py`，移除 session 逻辑
5. 测试后端启动

### Phase 2: 前端重构

1. 简化 `useStore.ts`，移除 session 状态
2. 简化 `ChatArea.tsx`，只做消息收发
3. 简化 `Sidebar.tsx`，移除 session 管理
4. 更新类型定义

### Phase 3: 清理

1. 删除 `session.py`
2. 删除 `database.py`
3. 删除 `models.py`（如果不再需要）
4. 测试完整流程

### Phase 4: 验证

1. WebSocket 连接测试
2. 消息收发测试
3. Memory 更新测试
4. Skills 加载测试
5. Summarization 触发测试

---

## 10. 风险与回退

**风险**:

- StoreBackend 是黑盒，调试困难
- 迁移过程中可能影响现有功能
- 前端改动较大

**回退方案**:

- 迁移前 git commit 当前状态
- 可以快速回退到 SQLite 版本

---

## 11. 验收标准

1. ✅ 后端能正常启动，DeepAgents agent 初始化成功
2. ✅ WebSocket 能建立连接并收发消息
3. ✅ Memory 系统能加载和更新 AGENTS.md
4. ✅ Skills 系统能加载技能文件
5. ✅ Summarization 能自动触发（token 超限时）
6. ✅ 前端能正常收发消息，UI 正常显示
7. ✅ 思考过程能正确分离和显示