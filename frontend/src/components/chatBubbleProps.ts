/**
 * ChatBubble 的 props 类型与自定义 memo 比较器。
 *
 * 拆出原因:ChatBubble.tsx 是纯组件文件,react-refresh ESLint 规则要求
 * "只导出组件";若同时导出 chatBubblePropsAreEqual 会被 lint 阻断。
 * 把比较器 + 类型拆到这里,组件文件只剩组件 export,符合 fast-refresh 约束。
 *
 * 自定义 memo 比较器 — 流式响应下,长对话列表里仅当前 chunk 命中 bubble
 * (id 相同的 message.content / thinking 在变)。其他已完成 bubble 的 props
 * 引用虽变(父级 re-render 传新 onCopy closure),但 content / thinking 字段
 * 走值相等,React 跳过它们的 reconciliation,ReactMarkdown 不重解析。
 *
 * 字段优先级:
 *  - id:同一消息在 streaming 中内容累计,id 不变 — 若 id 变说明换消息,必渲染
 *  - content / thinking:这两者变 = 流式追加或用户打字,需要更新 DOM
 *  - role:同一 id 的消息 role 不会变,但写入判定稳妥
 *  - showThinking / onCopy 引用变化不视为重渲染信号(parent re-render 无关)
 */
import type { Message } from '../types';

export interface ChatBubbleProps {
  message: Message;
  showThinking?: boolean;
  onCopy?: (content: string) => void;
}

export function chatBubblePropsAreEqual(
  prev: ChatBubbleProps,
  next: ChatBubbleProps,
): boolean {
  return (
    prev.message.id === next.message.id &&
    prev.message.role === next.message.role &&
    prev.message.content === next.message.content &&
    prev.message.thinking === next.message.thinking &&
    prev.showThinking === next.showThinking
  );
}