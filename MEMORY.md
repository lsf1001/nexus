---
name: nexus-technical-debt
description: Nexus 项目关键技术债和问题清单
metadata:
  type: project
---

# Nexus 核心问题分析 (2026/5/25)

## 来源

用户提供的详细技术债分析，来源: 2026/5/25 下午的会话总结

## 架构问题

### 1. 双 WebSocket 并行（死代码）

- `useWebSocket.ts` 是死代码，导出了 hook 但没有被 import
- 所有 WebSocket 逻辑在 `ChatArea.tsx` 里重复了一遍
- 两套 state 管理互不知情，session/思考内容 buffer 是两套并行状态

### 2. DeepAgents stream 格式黑盒

```python
for chunk in _agent.stream({"messages": history}, stream_mode="updates"):
    if "model" in chunk: ...
    elif "tool_call" in chunk: ...
    elif "tool_result" in chunk: ...
```

- 没有公开文档，key 全靠猜
- 其他格式 chunk 全部 `continue` 静默跳过
- **根本问题：丢 event 不报错，无法调试**

### 3. thinking 事件重复创建消息

```typescript
case 'thinking': {
    if (currentMessageIdRef.current) {
        updateMessage(...); // 追加 thinking
    } else {
        // 创建新消息 ← 每个 thinking 事件都走这条路径！
    }
}
```

- 一个思考过程 5 个事件 = 5 条消息碎片

### 4. chunk 事件 buffer 逻辑反转

```typescript
case 'chunk': {
    thinkingBufferRef.current += data.content;  // ← 累加到 thinkingBuffer
}
```

- chunk 应是 AI 回复片段，应该直接显示为 content
- thinkingBuffer 应是思考过程，两个东西混了

## 状态管理问题

### 5. 消息无上限积累

- `messages` 无限 append
- `get_conversation_history` 不截断，直接吐全部
- 聊 100 轮后 token 超限

### 6. thinking 内容碎片化

- thinking 事件被打散到 N 条 event
- 每条创建临时消息 ID，最后 `final` 才合并
- 过程中断了 thinking 就丢了

## 关键文件问题

| 文件                | 问题                             |
| ----------------- | ------------------------------ |
| 后端 main.py        | token 估算用正则数字符数，误差极大           |
| 后端 main.py        | 错误后 loop 继续，没有退出机制             |
| 后端 main.py        | 没有 session 级别 context 截断       |
| 后端 agent.py       | 系统提示词没有工作流边界                   |
| 后端 session.py     | `get_conversation_history` 不截断 |
| 前端 ChatArea.tsx   | `useEffect([])` cleanup 不完整    |
| 前端 ChatBubble.tsx | thinking 藏在 `<details>` 里默认折叠  |
| 前端 ChatBubble.tsx | 编辑模式点"发送"只更新 content，不发后端      |

## 核心感受

**DeepAgents stream event 格式不透明是一切问题的根源。**

要修：

1. 先摸清 DeepAgents 实际发的 event 格式
2. 后端和前端基于明确协议对齐
3. 消除死代码，统一 WebSocket 管理
4. 添加消息截断机制

## 优先级

P0（必须修）:

- chunk/思考 buffer 逻辑反转
- thinking 事件重复创建消息
- 消息无截断

P1（应该修）:

- 消除死代码
- 工具调用显示
- context 截断

P2（可以缓）:

- DeepAgents stream 格式摸清（需要阅读源码或实验）