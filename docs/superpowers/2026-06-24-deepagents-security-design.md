# DeepAgents 安全防护 + HITL 设计

**日期**:2026-06-24
**分支**:`feat/deepagents-security`
**范围**:Nexus 后端 WS HITL 桥接 + 前端确认卡片 + deepagents 0.6.8 FilesystemPermission 集成

---

## 目标

复用 deepagents 0.6.8 自带的 `FilesystemMiddleware` + `FilesystemPermission` +
`HumanInTheLoopMiddleware`,删除 Nexus 自带的 langchain_community 文件管理
工具,加 WS 层 HITL 桥接(GraphInterrupt → confirmation_request 帧 → 用户
决策 → `Command(resume=...)` 续流)。

## 三层防护

### 1. FilesystemPermission(框架内置,显式 allow / interrupt)

定义在 `nexus/backend/permissions.py::build_default_permissions`:
- **allow 读**:`/**`(LLM 可读任何文件)+ `/tmp/**`(LLM 可读 /tmp 临时文件)
- **allow 写**:`{project_root}/.nexus/**`(配置 / 日志 / outputs / state)
- **interrupt 写**:3 处 `AGENTS.md`(用户级 `~/.nexus/AGENTS.md` + 项目级
  `.nexus/AGENTS.md` + `.deepagents/AGENTS.md`)→ 触发 HITL

不引入 deny 规则(避免和 interrupt 语义重复 + 阻断 LLM 看到错误)。

注意:`/tmp` **只读不写**——LLM 可以看 /tmp 临时文件,但不允许写入
(产出物必须落 `.nexus/`,避免在 /tmp 散落不可审计文件)。

### 2. interrupt_on(框架内置,when 谓词兜底)

定义在 `nexus/backend/agent.py::build_interrupt_on_for_agent`:
- `write_file` / `edit_file` 工具:`when` 谓词判定目标路径
  - 在白名单内(`.nexus/**` 或 `/tmp/**`)→ 不 interrupt(layer 1 接管)
  - 是受保护 AGENTS.md → 不 interrupt(已由 layer 1 覆盖)
  - 其他(项目源码、用户家目录其他位置等)→ interrupt(触发 HITL)

macOS symlink 兜底:入口 `project_root.expanduser().resolve()` 与
`build_default_permissions` 对齐,避免 `/tmp` → `/private/tmp` 导致
白名单字符串与 target_path 解析后不一致。生产中 deepagents 框架传给
`when` 的 `target_path` 已经是 resolve 后的绝对路径,测试必须传入
resolve 后的字符串才能命中白名单。

### 3. QualityGateMiddleware(Nexus 自研,忠实度评估)

定义在 `nexus/backend/quality/middleware.py`:
- 拦截对 3 处 AGENTS.md 的 `edit_file` / `write_file`
- 用 `MemoryFilter` + `RubricJudge` + `FAITHFULNESS_RUBRIC` 评估内容忠实度
- 不通过则阻断并把原因回传 LLM 触发自我修正(独立于 HITL,作为第二道防线)

### 4. WS HITL 桥接(Nexus 自研,本 plan 实现)

**关键架构决策(plan Task 4 修订版)**:
- HITL 触发时 `langchain` 调 `langgraph.types.interrupt()` 挂起图
- 外层 `agent.astream_events()` **抛 `GraphInterrupt(interrupts=[...])`** 异常
  - `GraphInterrupt` 继承 `GraphBubbleUp`(`langgraph/errors.py:102`)
  - **不**作为普通 error 事件 yield,也不走重试
- `nexus/backend/resilience/stream_guard.py` 透传 `GraphInterrupt`:
  ```python
  except GraphInterrupt:  # noqa: PIE786
      raise
  ```
- `nexus/backend/api/ws.py::_run_agent_streaming` 捕获 `GraphInterrupt`:
  1. 把 `Interrupt.value`(标准 `hitl_request` dict,含 `action_requests`)透传
  2. 用 `_serialize_hitl_request` 转 WS `confirmation_request` 帧
  3. 写入 `_session_hitl_state[session_id] = {pending_interrupts, last_event_id}`
  4. 返回 5 元组 `(last_event_id, "", False, None, pending_interrupts)`
  5. `handle_websocket` 看到 `pending_interrupts` → 走 `_finalize_after_stream`
     的 HITL 挂起分支(early return,等 `confirmation_response`)

- 客户端发 `confirmation_response` 帧:
  1. `handle_websocket` 取出 `_session_hitl_state` 的 pending
  2. 装成 `resume_payload = {"decisions": [{"type": "approve"|"reject"}, ...]}`
  3. 第二次 `_run_agent_streaming(..., command_resume=resume_payload)`
  4. 内部改用 `agent.astream_events(Command(resume=...), config={thread_id: session_id})`
  5. checkpointer=`MemorySaver()`(in-process,进程重启即丢;升级 SqliteSaver
     留 follow-up)
  6. 续流后正常流式响应,经 `_finalize_after_stream` 统一收尾(质量门 / 入库 / done / emit ChatEnd)

### 5. 前端确认卡片(Task 5 实现)

定义在 `frontend/src/components/chat/ConfirmationCard.tsx`:
- 监听 WS `confirmation_request` 帧
- 渲染工具名 + 目标路径 + 描述
- 用户点击 approve/reject → 发 `confirmation_response` 帧回后端
- 与 `ClarificationCard` 互斥(同一时刻后端不会同时发两个)

`ChannelInbox` 通过 zustand selector 拿 `pendingConfirmation`,selector
必须返回稳定引用(避免返回新数组触发死循环——C5 漏修点)。

## 不在本 plan 范围

- MCP server 工具的危险操作过滤(独立 plan)
- execute shell 命令的 permission 拦截(deepagents 框架未实现,需自己写 sandbox backend)
- 跨会话审计日志(留 ops 阶段)
- SqliteSaver checkpointer 升级(留 follow-up,当前 `MemorySaver` 进程重启即丢 HITL 状态)
- `_session_hitl_state` 多进程支持(当前 in-process dict + RLock,分布式部署需重设计)

## 已知风险与边界

1. **MemorySaver 不持久**:WS 进程重启后,客户端发的 `confirmation_response` 找不到挂起状态
   - 降级:服务端返回 `no_pending_interrupt` error,客户端应重新发起 turn
2. **二次 HITL 触发**:LLM 在用户批准后又触发新 HITL(例如 approve 写 A.md 后又尝试写 B.md)
   - 行为:服务端把新 HITL 也写到 `_session_hitl_state`,客户端走第二轮确认
3. **前端 clarification + confirmation 互斥**:同一时刻后端若同时发两个,前端会同时显示两张卡片
   - 不属于本 plan 修复范围,属后端编排问题
4. **macOS symlink**:`/tmp` → `/private/tmp` 在所有路径处理入口都做了 `.expanduser().resolve()`
   兜底,确保字符串一致
5. **deepagents 内置 `interrupt_on` 与 Nexus 手动 `interrupt_on` 重复**:
   - `_build_interrupt_on_from_permissions` 自动把 FilesystemPermission mode="interrupt" 转 `interrupt_on`
   - 我们的 `build_interrupt_on_for_agent` 显式覆盖(`user-supplied entries win per tool`,
     `deepagents/graph.py:431`)
   - 冗余但显式化(plan 决策:白名单外全 HITL),未来如要简化可只保留自动部分

## 测试覆盖

- `tests/test_permissions.py`(Task 1):规则定义 + 受保护路径解析
- `tests/test_tools_registry.py`(Task 2):langchain_community 工具已删除,deepagents 接管
- `tests/test_agent_security.py`(Task 3):`create_agent` 启用 FilesystemPermission + interrupt_on
- `tests/test_ws_hitl.py`(Task 4):HITL 桥接 — `_serialize_hitl_request` /
  `_run_agent_streaming` / `handle_websocket` 6 个测试(含续流 LLM 响应丢失修复)
- `tests/test_security_e2e.py`(本 Task):端到端不变量 —
  3 处 AGENTS.md 都触发 interrupt / `.nexus/` 写 allow / `/tmp` 只读 /
  无 deny 规则 / `interrupt_on` 白名单放行 + 项目源码 HITL /
  `write_file` + `edit_file` 都装上 interrupt_on