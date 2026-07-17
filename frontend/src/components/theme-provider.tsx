import { useEffect, type ReactNode } from "react";
import { useStore } from "@/store"; // 复用既有的 darkMode 顶层字段

/**
 * 把 store 里的 darkMode 同步到 <html data-theme> 上,供全局 CSS 变量主题
 * (`:root[data-theme="dark"]`)切换。注意:desktop 的 useDarkModeRoot 也会写
 * 同一份 data-theme(挂在 .nexus-desktop 与 <html>),二者读同一个 store 值,
 * 重复但无害 —— 本 Provider 是面向全应用(含非 desktop 入口)的兜底同步。
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const darkMode = useStore((s) => s.darkMode);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", darkMode ? "dark" : "light");
  }, [darkMode]);

  return <>{children}</>;
}
