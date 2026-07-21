import { useEffect } from 'react';
import type { FontScale } from '@/store/slices/uiPrefs';

/**
 * useFontScaleRoot —— 把 store.fontScale 写入 :root + .nexus-desktop 的 --fs var。
 *
 * 镜像 useDarkModeRoot:dual-write + MutationObserver 防 React 重建 .nexus-desktop
 * 时把内联 style 擦掉。
 *
 * 不使用 data-font-scale attribute —— var(--fs) 直接被 token calc() 引用,
 * 无需 CSS 选择器间接桥接。
 */
export function useFontScaleRoot(scale: FontScale): void {
  useEffect(() => {
    const apply = (): void => {
      const root = document.querySelector<HTMLElement>('.nexus-desktop');
      const html = document.documentElement;
      const value = String(scale);
      root?.style.setProperty('--fs', value);
      html.style.setProperty('--fs', value);
    };

    apply();

    // React 19 在 loading → full 切换时会把 `.nexus-desktop` 整树重建,
    // 导致 inline style 丢失。监听 body 子树捕获节点替换,属性丢失时重写。
    const observer = new MutationObserver(() => {
      const root = document.querySelector<HTMLElement>('.nexus-desktop');
      if (root && !root.style.getPropertyValue('--fs')) {
        root.style.setProperty('--fs', String(scale));
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [scale]);
}
