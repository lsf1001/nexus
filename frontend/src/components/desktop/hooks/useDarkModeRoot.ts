import { useEffect } from 'react';

/**
 * 把 darkMode 状态同步到 CSS 选择器能识别的位置:
 *   1. .nexus-desktop 根元素(主选择器 `.nexus-desktop[data-theme="dark"]`)
 *   2. document.documentElement(<html>),作为冗余备份 —— 即便 React 把
 *      .nexus-desktop 整树重建(loading→full 切换),<html> 永远存在,
 *      CSS 也可以回退到 `:root[data-theme="dark"]` 分支。
 *
 * 必须在 .nexus-desktop 已挂载之后调用,通常在 DesktopShell 顶层。
 *
 * 关键:React 19 在 loading → full 切换时会把 `.nexus-desktop` 整树重建
 * (因为 loading state 返回的子结构跟 full state 差异大,React 放弃复用),
 * 导致 data-theme 属性丢失。解决办法:用 MutationObserver 监听 .nexus-desktop
 * 是否被替换,一旦发现新元素立刻重新应用 data-theme。
 */
export function useDarkModeRoot(darkMode: boolean): void {
  useEffect(() => {
    const apply = (): void => {
      const root = document.querySelector('.nexus-desktop');
      const html = document.documentElement;
      if (darkMode) {
        if (root) root.setAttribute('data-theme', 'dark');
        html.setAttribute('data-theme', 'dark');
      } else {
        if (root) root.removeAttribute('data-theme');
        html.removeAttribute('data-theme');
      }
    };

    apply();

    // 监听 body 子树,捕获 .nexus-desktop 节点被替换的瞬间
    const observer = new MutationObserver(() => {
      const root = document.querySelector('.nexus-desktop');
      const has = root?.getAttribute('data-theme');
      const expected = darkMode ? 'dark' : null;
      // 当 root 存在但属性不对(说明是新节点),立刻补上
      if (root && has !== expected) {
        apply();
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [darkMode]);
}
