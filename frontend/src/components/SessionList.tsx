import type { Conversation } from '../types';

interface SessionListProps {
  conversations: Conversation[];
  channel: 'main' | 'wechat';
  currentConversationId: string | null;
  darkMode: boolean;
  onSelect: (conv: Conversation) => void;
  onDelete: (id: string) => void;
}

/** 主会话/微信会话通用列表；空列表显示提示。 */
function SessionList({
  conversations,
  channel,
  currentConversationId,
  darkMode,
  onSelect,
  onDelete,
}: SessionListProps) {
  const filtered = conversations.filter(c =>
    channel === 'wechat' ? c.channel === 'wechat' : c.channel !== 'wechat',
  );
  const emptyHint = channel === 'wechat' ? '暂无微信会话' : '暂无主会话';

  if (filtered.length === 0) {
    return (
      <p className={`text-xs text-center py-4 ${darkMode ? 'text-gray-600' : 'text-[#a0a090]'}`}>
        {emptyHint}
      </p>
    );
  }

  return (
    <div className="space-y-1">
      {filtered.map(conv => {
        const active = currentConversationId === conv.id;
        return (
          <div
            key={conv.id}
            role="button"
            tabIndex={0}
            aria-label={`打开会话 ${conv.title}`}
            onClick={() => onSelect(conv)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onSelect(conv);
              }
            }}
            className={`group px-3 py-2 rounded-lg cursor-pointer transition-colors ${
              active
                ? darkMode ? 'bg-[#252525] text-white' : 'bg-[#e8ece5] text-[#2d4a3a]'
                : darkMode ? 'hover:bg-[#1a1a1a] text-gray-400' : 'hover:bg-[#f0f2ed] text-[#5a6b52]'
            }`}
          >
            <div className="text-sm truncate">{conv.title}</div>
            <div className="flex items-center justify-between mt-1">
              <span className={`text-xs ${darkMode ? 'text-gray-600' : 'text-[#8a9a7a]'}`}>
                {new Date(conv.updatedAt || conv.createdAt).toLocaleDateString()}
              </span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(conv.id);
                }}
                aria-label={`删除会话 ${conv.title}`}
                className={`opacity-0 group-hover:opacity-100 p-1 rounded transition-opacity ${darkMode ? 'hover:bg-red-900/30 text-red-500' : 'hover:bg-red-100 text-red-500'}`}
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default SessionList;
