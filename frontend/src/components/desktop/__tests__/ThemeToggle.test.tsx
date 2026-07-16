/**
 * ThemeToggle 单测 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop 在顶栏右侧放 ☀️ / 🌙 icon,点一下切换深色;
 *     state 走 useStore uiPrefs.darkMode + 已有 useDarkModeRoot 同步
 *     data-theme attribute。
 *
 * 契约:
 *   - 图标根据 darkMode 切换(浅 = 月亮,深 = 太阳)
 *   - 点 → store.toggleDarkMode()
 *   - 标签 `aria-pressed` 反映 darkMode 状态
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { ThemeToggle } from '../ThemeToggle';
import { useStore } from '../../../store';

describe('ThemeToggle (第九轮)', () => {
  beforeEach(() => {
    useStore.setState({ darkMode: false });
  });

  it('浅色模式时显示月亮图标(暗示可切到深色)', () => {
    useStore.setState({ darkMode: false });
    const { container } = render(<ThemeToggle />);
    const btn = container.querySelector('.theme-toggle');
    expect(btn?.textContent).toContain('🌙');
    expect(btn?.textContent).not.toContain('☀️');
  });

  it('深色模式时显示太阳图标', () => {
    useStore.setState({ darkMode: true });
    const { container } = render(<ThemeToggle />);
    const btn = container.querySelector('.theme-toggle');
    expect(btn?.textContent).toContain('☀️');
    expect(btn?.textContent).not.toContain('🌙');
  });

  it('点一下 → toggle darkMode', () => {
    useStore.setState({ darkMode: false });
    const { container } = render(<ThemeToggle />);
    const btn = container.querySelector('.theme-toggle') as HTMLElement;
    fireEvent.click(btn);
    expect(useStore.getState().darkMode).toBe(true);
  });

  it('再点 → toggle 回浅色', () => {
    useStore.setState({ darkMode: true });
    const { container } = render(<ThemeToggle />);
    const btn = container.querySelector('.theme-toggle') as HTMLElement;
    fireEvent.click(btn);
    expect(useStore.getState().darkMode).toBe(false);
  });

  it('aria-pressed 反映 darkMode 且随切换更新', () => {
    useStore.setState({ darkMode: true });
    const { container } = render(<ThemeToggle />);
    const btn = container.querySelector('.theme-toggle') as HTMLElement;
    expect(btn.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(btn);
    // 同一个 DOM 节点,rerender 之后属性跟随 store 更新
    expect(btn.getAttribute('aria-pressed')).toBe('false');
  });
});
