import {
  memo,
  useEffect,
  useRef,
  useState,
  useCallback,
  isValidElement,
} from 'react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Copy, Quote, RotateCw } from 'lucide-react';
import { useContextMenuTrigger } from '../lib/useContextMenuTrigger';
import { remarkPathLinkify } from '../lib/remarkPathLinkify';
import { ToolCallCard } from './ChatArea/ToolCallCard';
import {
  chatBubblePropsAreEqual,
  type ChatBubbleProps,
} from './chatBubbleProps';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from './ui/tooltip';

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

/** 递归提取 React 子树的纯文本(fenced code block 复制用)。 */
function extractText(node: ReactNode): string {
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (isValidElement(node)) {
    return extractText((node.props as { children?: ReactNode }).children);
  }
  return '';
}

/**
 * 代码块:低饱和蓝灰卡 + 右上角"已复制"微气泡(复制后 300ms 淡出)。
 * 不引入语法高亮依赖 —— "syntax-ish" 指蓝灰等宽 + 浅边框的观感,
 * 真正 token 着色留给后续任务。
 */
function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const onCopy = () => {
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(code).catch(() => {});
    }
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 300);
  };

  return (
    <div className="code-block">
      <button
        type="button"
        className="code-copy-btn"
        onClick={onCopy}
        aria-label="复制代码"
        title="复制代码"
      >
        <Copy size={13} aria-hidden="true" />
      </button>
      {copied && <span className="code-flash" aria-hidden="true">已复制</span>}
      <pre className="code-pre"><code>{code}</code></pre>
    </div>
  );
}

/** 悬停工具栏单按钮:shadcn Tooltip 包裹 icon 标签。 */
function ToolbarButton({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button type="button" className="toolbar-btn" onClick={onClick} aria-label={label}>
          {children}
        </button>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/** 内部函数组件 — 默认 export 用 React.memo 包装后导出。 */
function ChatBubbleInner({ message, showThinking = true, onCopy, onQuote, onRetry }: ChatBubbleProps) {
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

  // 复制"已复制"微气泡状态(消息级,300ms 淡出)
  const [copied, setCopied] = useState(false);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (copyTimer.current) clearTimeout(copyTimer.current);
  }, []);

  const flashCopy = useCallback(() => {
    setCopied(true);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    copyTimer.current = setTimeout(() => setCopied(false), 300);
  }, []);

  /** 构造复制/引用文本:思考 + 正文。 */
  const buildCopyText = useCallback(() => {
    const parts: string[] = [];
    if (message.thinking) parts.push(`[思考] ${message.thinking}`);
    if (message.content) parts.push(message.content);
    return parts.join('\n\n');
  }, [message.thinking, message.content]);

  const handleCopy = useCallback(() => {
    const text = buildCopyText();
    if (onCopy) onCopy(text);
    else if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(() => {});
    }
    flashCopy();
  }, [onCopy, buildCopyText, flashCopy]);

  const handleQuote = useCallback(() => {
    const text = buildCopyText();
    if (onQuote) {
      onQuote(text);
      flashCopy();
      return;
    }
    // 自包含回退:把消息引用(> 前缀)写入剪贴板,无需父级接线
    const quoted = text.split('\n').map((l) => `> ${l}`).join('\n');
    if (typeof navigator !== 'undefined' && navigator.clipboard) {
      navigator.clipboard.writeText(quoted).catch(() => {});
    }
    flashCopy();
  }, [onQuote, buildCopyText, flashCopy]);

  const handleRetry = useCallback(() => {
    onRetry?.();
  }, [onRetry]);

  const timestamp = message.createdAt ? formatTimestamp(message.createdAt) : '';

  // 右击消息任意位置 → 弹"复制 消息"菜单(user / assistant 都支持)
  const handleContextMenu = useContextMenuTrigger(buildCopyText, {
    label: isUser ? '消息' : '回复',
  });

  return (
    <div className={`message-row ${roleClass}`} data-role={message.role}>
      <div
        className={`message-bubble group ${isUser ? 'message-user' : 'message-assistant'}`}
        onContextMenu={handleContextMenu}
      >
        {/* 悬停工具栏:Copy / Quote / Retry,从右侧滑入,group-hover 显隐 */}
        <div className="hover-toolbar" role="toolbar" aria-label="消息操作">
          <TooltipProvider delayDuration={300}>
            <ToolbarButton label="复制" onClick={handleCopy}>
              <Copy size={14} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton label="引用" onClick={handleQuote}>
              <Quote size={14} aria-hidden="true" />
            </ToolbarButton>
            <ToolbarButton label="重试" onClick={handleRetry}>
              <RotateCw size={14} aria-hidden="true" />
            </ToolbarButton>
          </TooltipProvider>
        </div>
        {copied && <span className="copy-flash" aria-hidden="true">已复制</span>}

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
                const { href, children } = props as { href?: string; children?: ReactNode };
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
              // fenced code block → 蓝灰卡 + 复制微气泡
              pre: ({ children }) => <CodeBlock code={extractText(children)} />,
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
 * 注:`onCopy` / `onQuote` / `onRetry` 引用变化被刻意忽略 — MessageList 每次
 * re-render 会传新 closure,但复制/引用/重试回调的"是否执行"逻辑跟父级
 * re-render 无关,这个开销换 memo 命中很值。
 */
const ChatBubble = memo(ChatBubbleInner, chatBubblePropsAreEqual);

export default ChatBubble;
