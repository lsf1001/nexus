/**
 * wsHandlers 直接单测 — handleFinal 的 user-stopped gate(2026-07-13)
 *
 * 复现 e2e journey-stop-mid-stream 暴露的 bug:handleFinal 直接写
 * useStore.setState 覆盖最后一条 assistant 的 content,会绕过
 * useChatStream.appendToAssistant 的 stoppedRef gate,把"已停止"marker
 * 抹掉。修复:handleFinal 写 store 前查 store.streamingPaused;为 true
 * 时只 disarm + setIsLoading(false),不改 store,marker 保留。
 *
 * 2026-07-20:gate 从 useChatStream 内部 stoppedRef 升级为
 * useStore.streamingPaused,handler 直接读 store state,本测试同步切换
 * setStreamingPaused 切 gate。
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useStore } from '../../../store';
import { handleFinal } from '../hooks/wsHandlers';
import type { WsRouterCtx } from '../hooks/wsHandlers';

function makeCtx(
  setIsLoading: WsRouterCtx['setIsLoading'] = () => undefined,
  disarmWatchdog: WsRouterCtx['disarmWatchdog'] = () => undefined,
): WsRouterCtx {
  return {
    setLastError: () => undefined,
    setIsLoading,
    setPendingClarification: () => undefined,
    setPendingConfirmation: () => undefined,
    disarmWatchdog,
  };
}

describe('handleFinal — user-stopped gate', () => {
  beforeEach(() => {
    useStore.getState().setConversationMessages([]);
    useStore.setState({ streamingPaused: false });
  });

  it('未 streamingPaused 时 final 帧覆盖最后一条 assistant content', () => {
    useStore.getState().setConversationMessages([
      {
        id: 'a1',
        role: 'assistant',
        content: 'chunks 累计',
        createdAt: new Date(),
      },
    ]);

    const setIsLoading = vi.fn();
    const disarm = vi.fn();
    const ctx = makeCtx(setIsLoading, disarm);

    handleFinal({ type: 'final', content: 'quality pipeline 输出' }, ctx);

    const msgs = useStore.getState().conversationMessages;
    expect(msgs[0]?.content).toBe('quality pipeline 输出');
    expect(setIsLoading).toHaveBeenCalledWith(false);
    expect(disarm).toHaveBeenCalledTimes(1);
  });

  it('streamingPaused=true 时 final 帧不覆盖 store,保留"已停止"marker', () => {
    // 已点上 stop 的状态:最后一条 assistant 末尾被 handleStop 追加过 marker
    useStore.getState().setConversationMessages([
      {
        id: 'a1',
        role: 'assistant',
        content: '前方流内容\n\n_[已停止]_',
        createdAt: new Date(),
      },
    ]);
    useStore.setState({ streamingPaused: true });

    const setIsLoading = vi.fn();
    const disarm = vi.fn();
    const ctx = makeCtx(setIsLoading, disarm);

    // 服务端 final 帧仍到达,内容是 quality pipeline 输出(不等于已加 marker 的内容)
    handleFinal({ type: 'final', content: 'quality pipeline 输出' }, ctx);

    const msgs = useStore.getState().conversationMessages;
    // 关键断言:marker 必须保留,不被 final 覆盖
    expect(msgs[0]?.content).toContain('_[已停止]_');
    expect(msgs[0]?.content).not.toBe('quality pipeline 输出');
    // 但仍然 disarm + loading=false,让 UI 推进
    expect(setIsLoading).toHaveBeenCalledWith(false);
    expect(disarm).toHaveBeenCalledTimes(1);
  });

  it('conversationMessages 为空时 final 帧也不写 store(防御性)', () => {
    // 极端 case:final 帧先于任何 chunk 到达(conversationMessages.length === 0)
    const setIsLoading = vi.fn();
    const disarm = vi.fn();
    const ctx = makeCtx(setIsLoading, disarm);
    handleFinal({ type: 'final', content: 'should-be-ignored' }, ctx);
    expect(useStore.getState().conversationMessages).toEqual([]);
  });
});