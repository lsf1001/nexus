/**
 * ChatArea 顶层动作集成 hook。
 *
 * 把 ChatArea 内部原本散在 function body 的局部事件回调(handleKeyDown /
 * insertPrompt / handleCopyMessage / handleRetry)集中管理。这些动作都依赖
 * 上游 useState / useRef / useToast,抽出后让 ChatArea function body 真正只剩
 * React 顶层骨架(useState + 子组件 + JSX)。
 *
 * 不变性:行为与原 ChatArea 内部对应函数完全一致;deps 与原 useCallback 一一对应。
 */

import { useCallback } from 'react';
import { useStore } from '../../../store';
import { useToast } from '../../../store/useToast';
import type { ChatStreamActions } from './useChatStream';

export interface UseChatAreaActionsArgs {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  setInput: (next: string) => void;
  setIsLoading: (loading: boolean) => void;
  setLastError: (err: null) => void;
  send: (content: string) => void;
  stream: ChatStreamActions;
  armWatchdog: () => void;
}

export interface ChatAreaActions {
  handleKeyDown: (e: React.KeyboardEvent) => void;
  insertPrompt: (text: string) => void;
  handleCopyMessage: (content: string) => void;
  handleRetry: () => void;
}

export function useChatAreaActions(args: UseChatAreaActionsArgs): ChatAreaActions {
  const { inputRef, setInput, setIsLoading, setLastError, send, stream, armWatchdog } = args;
  const toast = useToast();

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        const ta = e.currentTarget as HTMLTextAreaElement;
        send(ta.value);
      }
    },
    [send],
  );

  const insertPrompt = useCallback(
    (text: string) => {
      setInput(text);
      inputRef.current?.focus();
    },
    [setInput, inputRef],
  );

  const handleCopyMessage = useCallback(
    (content: string) => {
      if (!navigator.clipboard) {
        toast.warn('当前环境不支持剪贴板 API');
        return;
      }
      navigator.clipboard.writeText(content).catch((err: unknown) => {
        const detail = err instanceof Error ? err.message : String(err);
        // 显式截断防泄漏(clipboard API 错误信息有时含 URL)。
        toast.error(`复制失败: ${(detail.split('\n')[0] ?? '').slice(0, 120)}`);
      });
    },
    [toast],
  );

  const handleRetry = useCallback(() => {
    const msgs = useStore.getState().conversationMessages;
    const lastUserMsg = [...msgs].reverse().find((m) => m.role === 'user');
    if (!lastUserMsg) return;
    setIsLoading(true);
    armWatchdog();
    setLastError(null);
    stream.replaceAssistantWithPlaceholder();
    send(lastUserMsg.content);
  }, [setIsLoading, armWatchdog, setLastError, stream, send]);

  return { handleKeyDown, insertPrompt, handleCopyMessage, handleRetry };
}
