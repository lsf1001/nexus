import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../../../lib/api';
import { useStore } from '../../../store/useStore';
import type { Conversation } from '../../../types';

const REQUEST_TIMEOUT_MS = 10_000;

export interface ConversationCrud {
  conversations: Conversation[];
  currentConversationId: string | null;
  resetCounter: number;
  onSelectConversation: (conv: Conversation) => void;
  onDeleteConversation: (id: string) => void;
  onNewTask: () => void;
  onSessionCreated: (sessionId: string, title: string) => void;
}

/**
 * 会话 CRUD + race-guard ref。
 * selectSessionRequestRef:快速点击同一会话时,只接受最新请求的结果,
 * 避免先点的慢请求覆盖后点的快结果(数据串台)。
 *
 * resetCounter:每次切换会话都 bump 一次,ChatArea 用它做 useEffect 依赖,
 * 触发对 messagesRef 的重新同步,避免上一个会话迟来的 chunk 写到新会话。
 */
export function useConversationCrud(): ConversationCrud {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [currentConversationId, setCurrentConversationId] = useState<string | null>(null);
  const [resetCounter, setResetCounter] = useState(0);

  const clearConversationMessages = useStore((state) => state.clearConversationMessages);
  const setConversationMessages = useStore((state) => state.setConversationMessages);

  const selectSessionRequestRef = useRef(0);

  const onSelectConversation = useCallback(
    async (conv: Conversation) => {
      const requestId = ++selectSessionRequestRef.current;
      setCurrentConversationId(conv.id);
      clearConversationMessages();
      setResetCounter((value) => value + 1);

      try {
        const controller = new AbortController();
        const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
        const response = await apiFetch(`/api/sessions/${conv.id}`, { signal: controller.signal });
        window.clearTimeout(timeout);
        const session = await response.json();
        // 若用户已切到其他会话,丢弃这个慢结果
        if (requestId !== selectSessionRequestRef.current) return;
        const messages = (session.messages || []).map((m: Record<string, unknown>) => ({
          id: String(m.id),
          role: m.role as 'user' | 'assistant',
          content: String(m.content ?? ''),
          thinking: m.thinking_content as string | undefined,
          createdAt: new Date(m.created_at as string),
        }));
        setConversationMessages(messages);
      } catch {
        if (requestId !== selectSessionRequestRef.current) return;
        // 网络失败时显式置空,避免 catch 内的 conv.messages 误把空数组写进 store
        setConversationMessages([]);
      }
    },
    [clearConversationMessages, setConversationMessages]
  );

  const onDeleteConversation = useCallback(
    async (id: string) => {
      try {
        await apiFetch(`/api/sessions/${id}`, { method: 'DELETE' });
      } catch {
        // 后端失败也接受(孤儿会话清理)
      }

      setConversations((previous) => previous.filter((conv) => conv.id !== id));
      if (currentConversationId === id) {
        setCurrentConversationId(null);
        clearConversationMessages();
        setResetCounter((value) => value + 1);
      }
    },
    [currentConversationId, clearConversationMessages]
  );

  const onNewTask = useCallback(() => {
    setCurrentConversationId(null);
    setResetCounter((value) => value + 1);
    clearConversationMessages();
    // 切到 chat 视图交给调用方决定(原 DesktopShell 调 setView('chat'))
  }, [clearConversationMessages]);

  const onSessionCreated = useCallback((sessionId: string, title: string) => {
    setCurrentConversationId(sessionId);
    setConversations((previous) => [
      {
        id: sessionId,
        title,
        messages: [],
        createdAt: new Date(),
        updatedAt: new Date().toISOString(),
        channel: 'main',
      },
      ...previous,
    ]);
  }, []);

  // 首启加载已存在的会话列表。
  // 之前 conversations 初始为 [] 没有任何 useEffect,导致 reload 后
  // 整个 sidebar "新任务" 之外的 history 全部丢失,必须从后端 /api/sessions 拉一次。
  useEffect(() => {
    let cancelled = false;
    const loadSessions = async (): Promise<void> => {
      try {
        const response = await apiFetch('/api/sessions?limit=50');
        if (!response.ok) return;
        const rows = (await response.json()) as Array<Record<string, unknown>>;
        if (cancelled) return;
        const loaded: Conversation[] = rows.map((row) => ({
          id: String(row.id),
          title: (row.title as string | null) ?? '新会话',
          messages: [], // 列表接口不返回 messages,点选时再 GET /api/sessions/{id}/messages
          createdAt: new Date((row.created_at as string | undefined) ?? Date.now()),
          updatedAt: (row.updated_at as string | undefined) ?? new Date().toISOString(),
          channel: (row.channel as string | undefined) ?? 'main',
        }));
        setConversations(loaded);
      } catch {
        // 拉取失败保留空列表,sidebar 走欢迎页空态即可,不要阻塞首屏
      }
    };
    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, []);

  return {
    conversations,
    currentConversationId,
    resetCounter,
    onSelectConversation,
    onDeleteConversation,
    onNewTask,
    onSessionCreated,
  };
}
