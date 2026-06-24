import { useState, useRef, useEffect, useCallback } from 'react';
import { useStore } from '../store/useStore';
import { openContextMenuAt } from '../lib/useContextMenuTrigger';
import { useWebSocket } from '../hooks/useWebSocket';
import { useLoadingWatchdog } from '../hooks/useLoadingWatchdog';
import ChatBubble from './ChatBubble';
import type { StreamEvent, WSMessage, Message, ConfirmationResponseFrame } from '../types';
import { getRuntimeToken } from '../lib/api';

interface ChatAreaProps {
  resetTrigger?: number;
  onConnectedChange?: (connected: boolean) => void;
  onSessionCreated?: (sessionId: string, title: string) => void;
  conversationId?: string | null;
  connectionState?: 'connecting' | 'online' | 'offline';
  activeConversationTitle?: string | null;
  conversationCount?: number;
}

const QUICK_PROMPTS: Array<{ title: string; prompt: string }> = [
  { title: '整理今天的待办', prompt: '请帮我整理今天的待办，提炼重点和下一步行动。' },
  { title: '总结微信里的消息', prompt: '请根据我最近的微信消息，帮我整理要点和待办。' },
  { title: '帮我写一封回复', prompt: '帮我起草一段专业又自然的回复。' },
  { title: '记住这个项目背景', prompt: '请记住这个项目的背景、目标和当前进度，下次对话时自动想起来。' },
];

interface LastError {
  message: string;
  retryable: boolean;
  code: string;
  at: number;
}

// === 澄清请求(LLM 主动追问) ===
interface PendingClarification {
  question: string;
  options: string[];   // 空数组 → 用户自由输入
}

const ERROR_MESSAGES: Record<string, string> = {
  'auth': 'API 密钥无效或已过期，请检查配置',
  'rate_limit_exhausted': '请求过于频繁，已重试多次仍失败，请稍后再试',
  'timeout_exhausted': '响应超时，请稍后再试或检查网络',
  'context_length': '对话过长，请开启新会话',
  'content_filter': '内容被安全策略拦截',
  'bad_request': '请求格式有误',
  'agent_unavailable': 'AI 服务暂未启动',
  'invalid_resume_token': '续传凭证已失效',
  'unknown': '未知错误',
};

function formatErrorMessage(code: string, raw: string): string {
  return ERROR_MESSAGES[code] ?? raw ?? '未知错误';
}

function ChatArea({
  resetTrigger,
  onConnectedChange,
  onSessionCreated,
  conversationId: conversationIdProp,
  connectionState = 'connecting',
  activeConversationTitle = null,
  conversationCount = 0,
}: ChatAreaProps) {
  const messagesRef = useRef<Message[]>([]);
  const [input, setInput] = useState('');
  const [lastError, setLastError] = useState<LastError | null>(null);
  const [pendingClarification, setPendingClarification] = useState<PendingClarification | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const resetTriggerRef = useRef(resetTrigger ?? 0);
  const sessionIdRef = useRef<string | null>(conversationIdProp);

  const isLoading = useStore((s) => s.isLoading);
  const wsConnected = useStore((s) => s.wsConnected);
  const showThinking = useStore((s) => s.showThinking);
  const setIsLoading = useStore((s) => s.setIsLoading);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const displayMessages = useStore((s) => s.conversationMessages);
  const setConversationMessages = useStore((s) => s.setConversationMessages);
  const clearConversationMessages = useStore((s) => s.clearConversationMessages);
  const modelName = useStore((s) => s.modelName);
  const pendingConfirmation = useStore((s) => s.pendingConfirmation);
  const setPendingConfirmation = useStore((s) => s.setPendingConfirmation);

  // 当 conversationId prop 变化时，同步更新 ref
  useEffect(() => {
    sessionIdRef.current = conversationIdProp;
  }, [conversationIdProp]);

  // 当 resetTrigger 变化时，重置所有消息状态
  useEffect(() => {
    if (resetTrigger && resetTrigger > resetTriggerRef.current) {
      messagesRef.current = [];
      clearConversationMessages();
      setInput('');
      setPendingClarification(null);
      setPendingConfirmation(null);
      setLastError(null);
    }
    resetTriggerRef.current = resetTrigger ?? 0;
  }, [resetTrigger, clearConversationMessages, setPendingConfirmation]);

  const handleWsMessage = useCallback((raw: StreamEvent | unknown) => {
    const data = raw as StreamEvent;
    if (!data || typeof data !== 'object' || !('type' in data)) return;
    // 通过 ref 调 disarm,避免 ChatArea render 期间因 TDZ 抛错
    const disarm = disarmWatchdogRef.current;

    // 容错：若流式事件先于 client 提交到达（罕见竞态：用户在
    // handleSend 之前 useEffect 还没跑，ws onmessage 已触发），
    // messagesRef 可能为空。补一个 assistant 占位消息，避免
    // chunk/thinking 被静默丢弃。
    const ensureAssistantPlaceholder = () => {
      if (messagesRef.current.length === 0) {
        messagesRef.current.push({
          id: crypto.randomUUID(),
          role: 'assistant',
          content: '',
          createdAt: new Date(),
        });
        setConversationMessages([...messagesRef.current]);
        return true;
      }
      return false;
    };

    switch (data.type) {
      case 'thinking': {
        ensureAssistantPlaceholder();
        if (messagesRef.current.length > 0) {
          const last = messagesRef.current[messagesRef.current.length - 1];
          if (last) {
            last.thinking = (last.thinking || '') + data.content;
            setConversationMessages([...messagesRef.current]);
          }
        }
        break;
      }
      case 'chunk': {
        setLastError(null);
        ensureAssistantPlaceholder();
        if (messagesRef.current.length > 0) {
          const last = messagesRef.current[messagesRef.current.length - 1];
          if (last && last.role === 'assistant') {
            last.content += data.content;
            setConversationMessages([...messagesRef.current]);
          }
        }
        break;
      }
      case 'final': {
        if (messagesRef.current.length > 0) {
          const last = messagesRef.current[messagesRef.current.length - 1];
          if (last) {
            // 服务端 final 帧的 content 是剥离 <thinking> 后的纯文本，
            // 在没有 quality pipeline 替换时应当等于 chunks 累积值；
            // 但若 quality pipeline 在 ws.py 中替换了内容，会先发一个 final 帧
            // （前一个 final 是 chunks 总和，这个 final 是 pipeline 替换后的内容）。
            // 因此：仅当 final 内容明显不同于当前累积值时，才覆盖（说明是 pipeline 替换）。
            const incoming = data.content || '';
            if (incoming && incoming !== last.content) {
              last.content = incoming;
              setConversationMessages([...messagesRef.current]);
            }
          }
        }
        setIsLoading(false);
        disarm();
        break;
      }
      case 'done': {
        setIsLoading(false);
        disarm();
        break;
      }
      case 'error': {
        setIsLoading(false);
        disarm();
        setLastError({
          message: data.content || '未知错误',
          retryable: data.retryable ?? false,
          code: data.error_code || 'unknown',
          at: Date.now(),
        });
        break;
      }
      case 'channel_message': {
        // 通道消息(wechat/feishu/telegram)不应进当前主会话(避免串台污染)。
        // 按 channel_type 分桶进 store.channelInbox,侧边栏收件箱图标显示
        // 对应通道的数量,用户主动点开对应通道视图才看具体内容。
        // 取代旧的 wechat_message 单通道帧(C5 重构)。
        const channelType = data.channel_type;
        if (!channelType) break;
        const { addChannelInbox } = useStore.getState();
        addChannelInbox(channelType, {
          id: crypto.randomUUID(),
          user_id: data.user_id || '',
          content: data.content || '',
          timestamp: Date.now(),
        });
        break;
      }
      case 'session_created': {
        onSessionCreated?.(data.session_id || '', data.title || '新会话');
        break;
      }
      case 'clarification_request': {
        // LLM 决定追问:弹澄清表单等用户回答,用户回答会作为新 turn 注入。
        // 注意:后端 clarification_request 帧**没有**发 final/done,本轮不算
        // 完成,所以这里要清掉 isLoading,否则 UI 一直转圈。
        //
        // 关键:后端会在 ws.py 562-563 行把 "[澄清中] {question}" 写进 DB,
        // 但 clarification_request 帧本身不带 assistant 占位文本,前端如果
        // 不补这条,UI 上 user 消息下面的 assistant 气泡就是空的——用户翻
        // 历史看不到"AI 刚才问了 X",只看到一张孤零零的选项卡,体验上像
        // 聊天记录被吞掉。这里把 handleSend 已经 push 的空 assistant 占位
        // 填上同样的 placeholder 文案,让 UI 与 DB 历史一致,会话回放时不丢
        // 上下文。
        setIsLoading(false);
        disarm();
        const question = (data.content || '').trim() || 'AI 需要你确认一项';
        const options = Array.isArray(data.options)
          ? data.options.filter((opt): opt is string => typeof opt === 'string' && opt.trim().length > 0).slice(0, 6)
          : [];
        if (messagesRef.current.length > 0) {
          const last = messagesRef.current[messagesRef.current.length - 1];
          if (last && last.role === 'assistant' && last.content === '') {
            last.content = `[澄清中] ${question}`;
            setConversationMessages([...messagesRef.current]);
          }
        }
        setPendingClarification({ question, options });
        break;
      }
      case 'confirmation_request': {
        // HITL 桥接:LLM 触发敏感操作(写文件 / 编辑 AGENTS.md 等),
        // 后端发 confirmation_request 等用户决策。与澄清路径类似:
        // 清 loading + disarm watchdog(避免 watchdog 30s 后误清状态
        // 把卡片也带走),然后渲染确认卡片,不调质量门 / done。
        //
        // 注意:与澄清不同,HITL 是阻断 LLM turn 的真正挂起点,用户
        // 点 approve/reject 后端会恢复执行;澄清是 LLM 主动追问,
        // 用户回答走自然 turn。这是两条独立路径。
        setIsLoading(false);
        disarm();
        if (!Array.isArray(data.actions) || data.actions.length === 0) {
          console.warn('confirmation_request 缺少 actions 字段,忽略');
          break;
        }
        setPendingConfirmation({
          interruptId: data.interrupt_id || '',
          eventId: data.event_id || 0,
          actions: data.actions,
        });
        break;
      }
    }
  }, [onSessionCreated, setConversationMessages, setIsLoading, setPendingConfirmation]);

  // === 客户端 watchdog:后端不发终止帧时强制清 loading ===
  // 必须在 handleWsMessage 之前声明 — useCallback 的 deps 数组在 render
  // 时立即求值,引用尚未声明的 const 会触发 TDZ ReferenceError。
  const { arm: armWatchdog, disarm: disarmWatchdog } = useLoadingWatchdog({
    setIsLoading,
    setLastError,
  });
  // 把 disarmWatchdog 也存进 ref,handleWsMessage (useCallback) 在 deps 之前
  // 也能通过 ref.current() 调用 — 双保险。
  const disarmWatchdogRef = useRef(disarmWatchdog);
  disarmWatchdogRef.current = disarmWatchdog;

  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/api/ws?token=${encodeURIComponent(getRuntimeToken())}`;
  const { connected: wsHookConnected, send: wsSend, getReadyState } = useWebSocket<StreamEvent>({
    url: wsUrl,
    onMessage: handleWsMessage,
  });

  const sendRef = useRef(wsSend);
  sendRef.current = wsSend;
  const getReadyStateRef = useRef(getReadyState);
  getReadyStateRef.current = getReadyState;

  useEffect(() => {
    setWsConnected(wsHookConnected);
    onConnectedChange?.(wsHookConnected);
  }, [wsHookConnected, setWsConnected, onConnectedChange]);

  useEffect(() => {
    // 有消息 → 滚到底部让最新消息可见。
    // 空态 → 不滚到底(那样会把 hero 推出视口);保持顶部对齐,让用户从
    // hero 开始浏览,自然向下看到 prompt 卡片和状态卡。如果整体溢出
    // chat-scroll,内容会自然延伸,用户可手动滚动查看。
    if (displayMessages.length > 0 || isLoading) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [displayMessages, isLoading]);

  const handleSend = () => {
    const messageContent = input.trim();
    if (!messageContent || !wsConnected) return;

    // 关键：发送前再确认 WS 真的 OPEN（避免"鬼影消息"）。
    // useWebSocket.send 在非 OPEN 时静默 no-op，handleSend 之前已经把
    // user+空 assistant 推到了 messagesRef 和 store，没了 response 也
    // 不会触发 error / done / final，用户卡死。必须前置校验。
    const readyState = getReadyStateRef.current();
    if (readyState !== WebSocket.OPEN) {
      setLastError({
        message: '连接尚未就绪，请稍后再试',
        retryable: true,
        code: 'ws_not_open',
        at: Date.now(),
      });
      return;
    }

    setIsLoading(true);
    armWatchdog();
    setLastError(null);
    setInput('');

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: messageContent,
      createdAt: new Date(),
    };
    messagesRef.current.push(userMsg);
    setConversationMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    };
    messagesRef.current.push(assistantMsg);
    setConversationMessages([...messagesRef.current]);

    const msg: WSMessage = { content: messageContent };
    if (!sessionIdRef.current) {
      msg.title = messageContent.slice(0, 30);
    } else {
      msg.session_id = sessionIdRef.current;
    }
    sendRef.current(msg);
  };

  // === 澄清回答提交 ===
  // 用户在澄清表单里选候选项 / 自由输入,作为普通用户消息发到后端,
  // 走主消息流。后端已有会话历史(包含"刚才问了 X"那行占位),
  // LLM 能自然接住继续原任务。
  const handleClarificationSubmit = (answer: string) => {
    const trimmed = answer.trim();
    if (!trimmed) return;
    if (!wsConnected) {
      setLastError({
        message: '连接尚未就绪，请稍后再试',
        retryable: true,
        code: 'ws_not_open',
        at: Date.now(),
      });
      return;
    }
    const readyState = getReadyStateRef.current();
    if (readyState !== WebSocket.OPEN) {
      setLastError({
        message: '连接尚未就绪，请稍后再试',
        retryable: true,
        code: 'ws_not_open',
        at: Date.now(),
      });
      return;
    }
    setPendingClarification(null);
    setIsLoading(true);
    armWatchdog();
    setLastError(null);

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: trimmed,
      createdAt: new Date(),
    };
    messagesRef.current.push(userMsg);
    setConversationMessages([...messagesRef.current]);

    const assistantMsg: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    };
    messagesRef.current.push(assistantMsg);
    setConversationMessages([...messagesRef.current]);

    const msg: WSMessage = { content: trimmed };
    if (sessionIdRef.current) {
      msg.session_id = sessionIdRef.current;
    }
    sendRef.current(msg);
  };

  const handleRetry = useCallback(() => {
    const lastUserMsg = [...messagesRef.current].reverse().find((m) => m.role === 'user');
    if (!lastUserMsg) return;
    setIsLoading(true);
    armWatchdog();
    setLastError(null);
    // 把最后一条 assistant 气泡**删掉**（无论空或满），避免重试后出现重复气泡。
    // 失败/中断时这个气泡要么空要么是上一次错误流留下的片段，直接重置最干净。
    const last = messagesRef.current[messagesRef.current.length - 1];
    if (
      messagesRef.current.length > 0 &&
      last !== undefined &&
      last.role === 'assistant'
    ) {
      messagesRef.current.pop();
    }
    // 推一个新空 assistant 占位，让 chunk/thinking 有地方写。
    messagesRef.current.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      createdAt: new Date(),
    });
    setConversationMessages([...messagesRef.current]);
    const msg: WSMessage = { content: lastUserMsg.content };
    if (sessionIdRef.current) msg.session_id = sessionIdRef.current;
    sendRef.current(msg);
  }, [setIsLoading, setConversationMessages, armWatchdog]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const insertPrompt = (text: string) => {
    setInput(text);
    inputRef.current?.focus();
  };

  const handleCopyMessage = (content: string) => {
    if (!navigator.clipboard) return;
    navigator.clipboard.writeText(content).catch((err) => {
      console.warn('复制失败:', err);
    });
  };

  const isIdle = displayMessages.length === 0 && !isLoading;
  const composerPlaceholder = wsConnected
    ? '告诉 Nexus 你想完成什么'
    : connectionState === 'offline'
      ? '本地助手离线，请先在设置中检查模型'
      : '正在连接本地助手...';

  return (
    <div className="chat-area">
      <div className="chat-scroll">
        {isIdle ? (
          <div className="empty-state">
            <div className="hero">
              <div className="eyebrow">个人任务助手</div>
              <h1>今天想让我帮你做什么？</h1>
              <p>
                Nexus 会在后台理解任务、选择模型、整理上下文和记录必要信息。
                你只需要把事情交给它。
              </p>
            </div>

            <div className="prompt-grid">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt.title}
                  type="button"
                  className="prompt-card"
                  onClick={() => insertPrompt(prompt.prompt)}
                  onContextMenu={(e) =>
                    openContextMenuAt(
                      e,
                      `${prompt.title}\n${prompt.prompt}`,
                      '速记'
                    )
                  }
                >
                  {prompt.title}
                </button>
              ))}
            </div>

            <div
              className="status-card"
              onContextMenu={(e) =>
                openContextMenuAt(
                  e,
                  [
                    '任务状态',
                    `助手: ${modelName || '未配置模型'}`,
                    `本地连接: ${connectionState === 'online' ? '运行中' : connectionState === 'connecting' ? '连接中' : '离线'}`,
                    `当前会话: ${activeConversationTitle || '新任务（未保存）'}`,
                    `最近任务: ${conversationCount} 条`,
                  ].join('\n'),
                  '状态'
                )
              }
            >
              <strong>任务状态</strong>
              <div className="row">
                <span className="label">助手</span>
                <span className="value">{modelName || '未配置模型'}</span>
              </div>
              <div className="row">
                <span className="label">本地连接</span>
                <span className="value">
                  <span className={`state-pill ${connectionState === 'online' ? '' : 'is-idle'}`}>
                    {connectionState === 'online' ? '运行中' : connectionState === 'connecting' ? '连接中' : '离线'}
                  </span>
                </span>
              </div>
              <div className="row">
                <span className="label">当前会话</span>
                <span className="value">{activeConversationTitle || '新任务（未保存）'}</span>
              </div>
              <div className="row">
                <span className="label">最近任务</span>
                <span className="value">{conversationCount} 条</span>
              </div>
            </div>
          </div>
        ) : (
          <div className="message-list">
            {displayMessages.map((msg) => (
              <ChatBubble
                key={msg.id}
                message={msg}
                showThinking={showThinking}
                onCopy={handleCopyMessage}
              />
            ))}
            {isLoading && (
              <div className="message-row is-assistant">
                <div className="loading-bubble" aria-label="助手正在输入">
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                  <span className="loading-dot" />
                </div>
              </div>
            )}
          </div>
        )}
        {pendingClarification && (
          <ClarificationForm
            question={pendingClarification.question}
            options={pendingClarification.options}
            onSubmit={handleClarificationSubmit}
            onCancel={() => setPendingClarification(null)}
          />
        )}
        {pendingConfirmation && (
          <div className="confirm-card" role="group" aria-label="AI 请求你确认一项操作">
            <div className="confirm-eyebrow">需要你确认</div>
            {pendingConfirmation.actions.map((action, idx) => (
              <div key={`${pendingConfirmation.interruptId}-${idx}`} className="confirm-action">
                <div className="confirm-action-header">
                  <code className="confirm-tool">{action.tool_name}</code>
                  <span className="confirm-target">{action.target_path}</span>
                </div>
                {action.description && (
                  <div className="confirm-description">{action.description}</div>
                )}
                {action.preview && (
                  <pre className="confirm-preview">{action.preview}</pre>
                )}
                <div className="confirm-actions">
                  {action.options.map((opt) => (
                    <button
                      key={opt.decision}
                      type="button"
                      className={`confirm-btn confirm-${opt.decision}`}
                      onClick={() => {
                        if (wsSend && getReadyState() === WebSocket.OPEN) {
                          wsSend({
                            type: "confirmation_response",
                            event_id: pendingConfirmation.eventId,
                            interrupt_id: pendingConfirmation.interruptId,
                            decision: opt.decision,
                          } as ConfirmationResponseFrame);
                        }
                        setPendingConfirmation(null);
                      }}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {lastError && (
        <div className="error-wrap">
          <div
            className={`error-banner ${lastError.retryable ? 'is-warn' : 'is-error'}`}
            role="alert"
          >
            <span className="icon">{lastError.retryable ? '⚠️' : '❌'}</span>
            <div className="body">
              <div className="title">{lastError.retryable ? '暂时不可用' : '请求失败'}</div>
              <div className="detail">
                {formatErrorMessage(lastError.code, lastError.message)}
              </div>
            </div>
            {lastError.retryable && (
              <button
                type="button"
                className="retry-btn"
                onClick={() => {
                  setLastError(null);
                  handleRetry();
                }}
              >
                重试
              </button>
            )}
            <button
              type="button"
              className="close-btn"
              onClick={() => setLastError(null)}
              aria-label="关闭错误提示"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      <div className="composer-wrap">
        <div className="composer-shell">
          <div className="composer">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              onContextMenu={(e) => openContextMenuAt(e, input, '草稿')}
              placeholder={composerPlaceholder}
              disabled={!wsConnected}
              rows={3}
              className="composer-textarea"
            />
            <div className="composer-bottom">
              <span className="hint">
                {isLoading ? '正在生成中...可继续输入下一条' : '个人任务助手 · 本地运行'}
              </span>
              <button
                type="button"
                onClick={handleSend}
                disabled={!wsConnected || !input.trim() || isLoading}
                className="send-button"
                aria-label="发送消息"
                title={isLoading ? '请等待当前回复完成' : '发送消息'}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ChatArea;

// === 澄清表单 ===
// LLM 主动追问时弹出:有候选项时显示选项按钮,无候选项时显示自由输入框。
// 用户提交后由 ChatArea 的 handleClarificationSubmit 走主消息流。
interface ClarificationFormProps {
  question: string;
  options: string[];
  onSubmit: (answer: string) => void;
  onCancel: () => void;
}

function ClarificationForm({ question, options, onSubmit, onCancel }: ClarificationFormProps) {
  const [freeText, setFreeText] = useState('');
  const hasOptions = options.length > 0;
  const submitFree = () => {
    const value = freeText.trim();
    if (!value) return;
    onSubmit(value);
  };

  return (
    <div className="clarify-card" role="group" aria-label="AI 正在向你确认">
      <div className="clarify-eyebrow">需要你确认</div>
      <div className="clarify-question">{question}</div>
      {hasOptions ? (
        <div className="clarify-options">
          {options.map((option) => (
            <button
              key={option}
              type="button"
              className="clarify-option"
              onClick={() => onSubmit(option)}
            >
              {option}
            </button>
          ))}
          <details className="clarify-free-toggle">
            <summary>自己写回答</summary>
            <div className="clarify-free">
              <textarea
                value={freeText}
                onChange={(e) => setFreeText(e.target.value)}
                placeholder="输入你的回答..."
                rows={2}
                className="clarify-textarea"
              />
              <button
                type="button"
                className="clarify-submit"
                onClick={submitFree}
                disabled={!freeText.trim()}
              >
                发送
              </button>
            </div>
          </details>
        </div>
      ) : (
        <div className="clarify-free">
          <textarea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder="输入你的回答..."
            rows={3}
            className="clarify-textarea"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                submitFree();
              }
            }}
          />
          <div className="clarify-actions">
            <button type="button" className="clarify-cancel" onClick={onCancel}>
              取消
            </button>
            <button
              type="button"
              className="clarify-submit"
              onClick={submitFree}
              disabled={!freeText.trim()}
            >
              发送
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
