/**
 * MessageList memo 比较器 — 单独拆出文件以便测试 import。
 *
 * WHY 拆出:MessageList.tsx 是纯组件文件,react-refresh ESLint 规则要求
 * "只导出组件";若同时导出 messageListPropsAreEqual 会被 lint 阻断。
 * 把比较器拆到这里,组件文件只剩组件 export,符合 fast-refresh 约束。
 *
 * 设计要点:
 * - 流式响应期间每帧 appendAssistantPatch 都 `setConversationMessages(cloned)`,
 *   messages 数组引用每帧变化。
 * - 原设计只比较前 N-1 条引用相等 → MessageList memo skip → ChatBubble 拿不到
 *   新 props → 末条 content 增量被吞。
 * - 修法:除前 N-1 条引用相等外,也按值比较最后一条的 content / thinking / toolCalls。
 *   任一字段值变化 → 返回 false → MessageList 重渲染 → ChatBubble memo 默认
 *   比较器看到 message.content 不同 string → 重渲染 → DOM 更新。
 *
 * 字段选择理由:
 * - content:流式 chunk 的核心数据,增量追加。
 * - thinking:思考块长度增长,长度变化需更新折叠卡片 N 字标签。
 * - toolCalls:tool_call / tool_result 帧到达时整个数组引用变化,需要触发 render
 *   让 ToolCallCard 列表对齐。
 * - role / id / createdAt:同 id 的消息这些字段不会变,可比可不比,留给 ChatBubble
 *   memo 决定。
 */
import type { Message } from '../../types';

export interface MessageListProps {
  messages: ReadonlyArray<Message>;
  showThinking: boolean;
  isLoading: boolean;
  onCopy?: (content: string) => void;
  onRetry?: () => void;
}

export function messageListPropsAreEqual(
  prev: MessageListProps,
  next: MessageListProps,
): boolean {
  if (prev.isLoading !== next.isLoading) return false;
  if (prev.showThinking !== next.showThinking) return false;
  const pm = prev.messages;
  const nm = next.messages;
  if (pm.length !== nm.length) return false;
  const len = pm.length;
  for (let i = 0; i < len - 1; i++) {
    if (pm[i] !== nm[i]) return false;
  }
  if (len > 0) {
    const pl = pm[len - 1]!;
    const nl = nm[len - 1]!;
    if (
      pl.content !== nl.content ||
      pl.thinking !== nl.thinking ||
      pl.toolCalls !== nl.toolCalls
    ) {
      return false;
    }
  }
  return true;
}