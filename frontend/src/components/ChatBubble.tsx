import { memo, useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useContextMenuTrigger } from '../lib/useContextMenuTrigger';
import { remarkPathLinkify } from '../lib/remarkPathLinkify';
import { ToolCallCard } from './ChatArea/ToolCallCard';
import {
  chatBubblePropsAreEqual,
  type ChatBubbleProps,
} from './chatBubbleProps';

/** 第九轮(2026-07-16):思考块折叠偏好 — localStorage key,
 * 用户上次展开/折叠决定下次默认状态。
 * WHY:Claude Desktop / ChatGPT 形态。 */
const THINKING_EXPANDED_KEY = 'nexus_thinking_expanded';

function readThinkingPref(): boolean {
  try {
    return localStorage.getItem(THINKING_EXPANDED_KEY) === 'true';
  } catch {
    return false;
  }
}

/** 友好时间格式:今天 HH:MM / 昨天 HH:MM / YYYY-MM-DD HH:MM */
function formatTimestamp(d: Date): string {
  const now = new Date();
  const sameDay = (a: Date, b: Date) =>
    a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const pad = (n: number) => String(n).padStart(2, '0');
  const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  if (sameDay(d, now)) return `今天 ${hm}`;
  if (sameDay(d, yesterday)) return `昨天 ${hm}`;
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hm}`;
}

/** 内部函数组件 — 默认 export 用 React.memo 包装后导出。 */
function ChatBubbleInner({ message, showThinking = true, onCopy }: ChatBubbleProps) {
  const isUser = message.role === 'user';
  const roleClass = isUser ? 'is-user' : 'is-assistant';

  // 第九轮:思考块折叠 — localStorage 持久化用户偏好,默认折叠
  const [thinkingExpanded, setThinkingExpanded] = useState<boolean>(() => readThinkingPref());
  useEffect(() => {
    try {
      localStorage.setItem(THINKING_EXPANDED_KEY, String(thinkingExpanded));
    } catch {
      // localStorage 不可用,降级为内存态
    }
  }, [thinkingExpanded]);

  const handleCopy = () => {
    const text = message.content || message.thinking || '';
    onCopy?.(text);
  };

  const timestamp = message.createdAt ? formatTimestamp(message.createdAt) : '';

  // 右击消息任意位置 → 弹"复制 消息"菜单（user / assistant 都支持）
  const handleContextMenu = useContextMenuTrigger(
    () => {
      const parts: string[] = [];
      if (message.thinking) parts.push(`[思考] ${message.thinking}`);
      if (message.content) parts.push(message.content);
      return parts.join('\n\n');
    },
    { label: isUser ? '消息' : '回复' }
  );

  return (
    <div className={`message-row ${roleClass}`}>
      <div
        className={`message-bubble ${isUser ? 'message-user' : 'message-assistant'}`}
        onContextMenu={handleContextMenu}
      >
        {!isUser && onCopy && (
          <button
            onClick={handleCopy}
            className="copy-button"
            type="button"
            title="复制内容"
            aria-label="复制消息"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
              <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
            </svg>
          </button>
        )}
        {showThinking && message.thinking && (
          <div className="thinking-card">
            <button
              type="button"
              className="thinking-toggle"
              onClick={() => setThinkingExpanded((v) => !v)}
              aria-expanded={thinkingExpanded}
              aria-label={thinkingExpanded ? '收起思考过程' : '展开思考过程'}
            >
              <span aria-hidden="true">🌿</span>
              <span>{thinkingExpanded ? '收起思考过程' : `已思考 ${message.thinking.length} 字 · 点开看`}</span>
              <span aria-hidden="true" className={`thinking-chevron ${thinkingExpanded ? 'is-open' : ''}`}>
                {thinkingExpanded ? '▾' : '▸'}
              </span>
            </button>
            {thinkingExpanded && (
              <pre className="thinking-content">{message.thinking}</pre>
            )}
          </div>
        )}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="message-tool-calls">
            {message.toolCalls.map((tc) => (
              <ToolCallCard key={tc.id} call={tc} />
            ))}
          </div>
        )}
        <div className={`message-markdown ${isUser ? 'user' : 'assistant'}`}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkPathLinkify]}
            urlTransform={(value) => {
              // react-markdown 默认 urlTransform 不放行 file:// / blob: 等"非主流"协议
              // (白名单只含 https?|ircs?|mailto|xmpp),会把 src/href 抹空。
              // 这里放行:file://(浏览器/Preview 打开本地文件)、
              //         http://asset.localhost(Tauri asset protocol,见 tauri.conf.json assetProtocol)、
              //         http(s)://(外链)、相对路径、# 锚点。
              // 其他协议仍交给默认行为抹空(防御 javascript: 等 XSS 注入)。
              if (value.startsWith('file://')) return value;
              if (value.startsWith('http://asset.localhost')) return value;
              if (/^https?:\/\//i.test(value)) return value;
              if (/^[/.]/.test(value) || value === '#') return value;
              return '';
            }}
            components={{
              a: (props) => {
                const { href, children } = props as { href?: string; children?: React.ReactNode };
                return (
                  <a
                    href={href ?? '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="file-link"
                  >
                    {children}
                  </a>
                );
              },
              img: ({ src, alt }) => (
                // file:// 缩略图 — macOS Electron WebView 不允许 http→file 加载,
                // 但 Electron WebView 默认允许 file→file 直接 fetch(local resource)。
                // 设置 loading=lazy 避免长对话 100+ 张图片同时加载。
                <img src={src} alt={alt} className="file-image" loading="lazy" />
              ),
            }}
          >{message.content}</ReactMarkdown>
        </div>
      </div>
      {timestamp && <div className={`message-timestamp ${roleClass}`}>{timestamp}</div>}
    </div>
  );
}

/**
 * React.memo 包装 + 自定义相等比较器:
 * - 长对话(100+ 条)+ 流式响应(60 chunks/s)下,绝大多数已完成的 ChatBubble
 *   content / thinking 已稳定,memo 直接跳过,ReactMarkdown 不重解析。
 * - 当前活跃 chunk 的 bubble props 变化(content / thinking 增量)→ 走重渲染。
 *
 * 注:`onCopy` 引用变化被刻意忽略 — MessageList 每次 re-render 会传新 closure,
 * 但复制回调的"是否执行"逻辑跟父级 re-render 无关,这个开销换 memo 命中很值。
 */
const ChatBubble = memo(ChatBubbleInner, chatBubblePropsAreEqual);

export default ChatBubble;