/**
 * 自动滚动 hook。
 *
 * 设计:
 *   - trigger(messages.length / isLoading)变化时,滚动容器(.chat-scroll,必须
 *     overflow:auto)对齐到底部
 *   - 用 RAF 合并单次 render 内多次 trigger
 *   - 2026-07-13 用户主动滚动覆盖:监听 wheel / touchmove / scrollbar drag,
 *     标记 userScrolledUp=true。新消息触发滚动时,userScrolledUp=true 就不拽回
 *     底部(用户在主动看历史);false 就滚到底。距离底部 <= 8px 时重置
 *     userScrolledUp=false — 用户滚回去看新内容时,后续新消息又能自动滚到底。
 *   - 2026-07-13 真 LLM multi-turn 暴露 viewport ratio 0:容器 ref 必须用
 *     callback ref(React.RefObject 的 .current 不是响应式值,容器节点被 React
 *     替换后旧 listener 仍挂死节点)。改 callback ref,容器 mount/unmount 自动
 *     重绑。
 *   - 2026-07-13 同一次修复:smooth scroll 在 rAF 内被 cancelAnimationFrame
 *     反复撤销,实测 scrollTop 一直为 0。改 'instant'(同步)— 多轮 LLM 流速下
 *     "顿挫感"对人眼不可察,可测试性大幅提升。
 *
 * WHY 区分 wheel / scrollTo:JS 触发的 scrollTo 会派发 scroll 事件,但不是
 * 用户主动行为。event.isTrusted 最稳(UserGesture API 标记):浏览器对所有
 * wheel / touch / keyboard scroll 置 isTrusted=true,JS scrollTo /
 * scrollIntoView 置 false。
 */

import { useEffect, useRef } from 'react';

export interface UseAutoScrollArgs {
  /** 触发滚动的依赖数组(典型:消息数 + loading) */
  trigger: ReadonlyArray<unknown>;
  /** 滚动容器 ref — 必须指向 overflow:auto 的 .chat-scroll 自身。
   *  如果误指向无 overflow 的末尾空 div(如 messagesEndRef),scrollTo 不会带动
   *  父容器,viewport 不动,2026-07-13 真 LLM multi-turn 暴露 viewport ratio 0
   *  就是这个错。 */
  containerRef: React.RefObject<HTMLElement | null>;
}

/**
 * 自动滚动 hook — 等价于 ChatArea 旧的 useEffect + messagesEndRef.scrollIntoView,
 * 但用 rAF 节流 + 尊重用户主动滚动覆盖。
 */
export function useAutoScroll({
  trigger,
  containerRef,
}: UseAutoScrollArgs): void {
  const rafRef = useRef<number | null>(null);
  // 用户主动滚轮 / touch / scrollbar drag 标记。JS scrollTo 不计(isTrusted=false)。
  const userScrolledUpRef = useRef(false);
  // 滚动容器节点 — 用 callback ref 直接捕获,避免 .current 反应性陷阱。
  const scrollElRef = useRef<HTMLElement | null>(null);

  // 监听滚动(用户主动滚 vs JS 触发)
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    scrollElRef.current = el;
    const onScroll = (ev: Event) => {
      // 只有用户手势触发的 scroll 才算"主动滚"
      if (!ev.isTrusted) return;
      const distanceToBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      // 用户已经回到贴底位置 → 重置标记,后续新消息继续自动滚
      if (distanceToBottom <= 8) {
        userScrolledUpRef.current = false;
        return;
      }
      userScrolledUpRef.current = true;
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      el.removeEventListener('scroll', onScroll);
    };
  }, [containerRef]);

  // trigger 变化 → 滚到底部(贴底 + 用户未主动滚的情况下)
  useEffect(() => {
    // 跳过首屏(empty-state 由 hero 控制对齐,不滚)
    if (trigger.length === 0) return undefined;
    const doScroll = () => {
      const el = scrollElRef.current ?? containerRef.current;
      if (el) {
        // 用户主动滚上去了,不要硬拽回去
        if (userScrolledUpRef.current) return;
        // 设置 scrollTop 到 scrollHeight 即可。
        // 关键:必须拉到 max scrollTop —— scrollHeight 在 rAF 后可能还增长
        // (LLM 流最后 chunk 没到),所以同一帧设两次,先让浏览器 paint,再
        // 拿最新 scrollHeight 设一次。2026-07-13 真 LLM multi-turn 第二轮起
        // 只滚一次会停在 rAF 内的中间高度,后续 chunk 撑出滚动条后 scrollTop
        // 永远追不上,viewport ratio 0。
        el.scrollTop = el.scrollHeight;
        requestAnimationFrame(() => {
          el.scrollTop = el.scrollHeight;
        });
      }
    };
    rafRef.current = window.requestAnimationFrame(doScroll);
    return () => {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, trigger);
}
