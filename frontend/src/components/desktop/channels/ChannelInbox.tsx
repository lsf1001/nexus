/**
 * ChannelInbox - 共享收件箱,所有通道的消息都汇入这里。
 *
 * 通过 store channelInbox (Record<channelType, Msg[]>) 取数,
 * 按 channelType 过滤显示。每个 channelType 一个 ChannelInbox 实例,
 * 父组件 (ChannelViewBase) 决定传哪个 type。
 *
 * 清空通过 store.clearChannelInbox(channelType) 完成,
 * 清空语义是"标记已读",下次 mount 或下次有新消息再继续累加。
 */

import { useStore } from '../../../store/useStore';
import type { ChannelInboxMsg } from '../../../store/useStore';
import type { ChannelType } from '../../../types';

interface ChannelInboxProps {
  channelType: ChannelType;
}

// 模块级常量,避免 zustand selector 每次返回新引用触发"Maximum update depth
// exceeded"无限重渲染。selector 必须返回稳定引用,否则 zustand 误判状态变更
// → 组件 re-render → selector 再次返回新引用 → 死循环。
const EMPTY_INBOX: readonly ChannelInboxMsg[] = [];

export function ChannelInbox({ channelType }: ChannelInboxProps) {
  const inbox = useStore((state) => state.channelInbox[channelType] ?? EMPTY_INBOX);
  const clearInbox = useStore((state) => state.clearChannelInbox);

  if (inbox.length === 0) {
    return (
      <div className="channel-inbox-empty">
        暂无 {channelType} 通道消息
      </div>
    );
  }

  return (
    <div className="channel-inbox">
      <button type="button" onClick={() => clearInbox(channelType)}>清空</button>
      <ul>
        {inbox.map((msg) => (
          <li key={msg.id} className="channel-inbox-item">
            <div className="channel-inbox-user">{msg.user_id}</div>
            <div className="channel-inbox-content">{msg.content}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}
