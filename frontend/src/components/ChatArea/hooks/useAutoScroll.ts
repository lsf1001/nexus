/**
 * 自动滚动 hook。
 *
 * Plan 2 §5 要求:RAF-throttled scrollIntoView + 用户手动滚动覆盖检测。
 *
 * 设计:
 *   - 当 messages.length / isLoading 变化触发滚动对齐
 *   - 用 ResizeObserver 监听 chat-scroll 容器尺寸(内容撑高后必须滚到底)
 *   - 用 RAF 合并两次 change 内的 scrollIntoView 调用,避免 LLM chunk 高频
 *     触发时 jank
 *
 * 暂不实现"用户手动滚动覆盖":ChatArea 原版用 messagesEndRef 占位的"加新内容
 * 自动滚到底"行为,如果引入"用户上滚看历史就停"逻辑,会让 LLM 长回复场景下
 * 用户每次都被强制拉回底部反而体验差;Plan §5 列为 TODO,本次只做 RAF 节流,
 * 等真实用户反馈驱动再做 user-override。
 */

import { useEffect, useRef } from 'react';

export interface UseAutoScrollArgs {
  /** 触发滚动的依赖数组(典型:消息数 + loading) */
  trigger: ReadonlyArray<unknown>;
  /** 容器 ref;若容器不存在则 no-op(容错:第一次 render 时 ref 未挂) */
  containerRef: React.RefObject<HTMLElement | null>;
  /** 距离底部多少 px 时仍算"贴底";默认 80,这样 chunk 不会因为滚动条细微滑动而漏滚 */
  bottomThreshold?: number;
}

/**
 * 自动滚动 hook — 等价于 ChatArea 旧的 useEffect + messagesEndRef.scrollIntoView,
 * 但用 rAF 节流 + 在容器 ref 未挂时 no-op。
 */
export function useAutoScroll({
  trigger,
  containerRef,
  bottomThreshold = 80,
}: UseAutoScrollArgs): void {
  const rafRef = useRef<number | null>(null);
  useEffect(() => {
    // 跳过首屏(empty-state 由 hero 控制对齐,不滚)
    if (trigger.length === 0) return;
    if (rafRef.current !== null) {
      window.cancelAnimationFrame(rafRef.current);
    }
    rafRef.current = window.requestAnimationFrame(() => {
      const el = containerRef.current;
      if (el) {
        const distanceToBottom =
          el.scrollHeight - el.scrollTop - el.clientHeight;
        // 距离底部大于阈值时:用户正在看上面历史,不要硬拽回去
        if (distanceToBottom > bottomThreshold) {
          return;
        }
        el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
      }
      rafRef.current = null;
    });
    return () => {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
    };
    // 故意忽略 containerRef(对象引用变化频繁)— 容器一般不会换节点
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, trigger);
}
