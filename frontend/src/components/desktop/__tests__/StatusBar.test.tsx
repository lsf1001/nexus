/**
 * StatusBar 单元测试 — 2026-07-23 #2 修复锁测。
 *
 * 契约:StatusBar 是「模型 + 连接」在主界面的唯一可见位置(2026-07-21 决策)。
 *   - modelName 存在 → 渲染在状态栏内(带 title 提示)
 *   - modelName 空 → 不渲染模型名 span(仅保留连接点 + local)
 */
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { StatusBar } from '../StatusBar';
import { useStore } from '../../../store';

describe('StatusBar — 显示当前模型名(#2)', () => {
  it('modelName 存在 → 渲染在状态栏内', () => {
    useStore.setState({ modelName: 'claude-sonnet-4-6' });
    render(<StatusBar wsConnected={true} modelConfigured={true} />);
    expect(screen.getByText('claude-sonnet-4-6')).toBeInTheDocument();
  });

  it('modelName 空 → 不渲染模型名', () => {
    useStore.setState({ modelName: '' });
    render(<StatusBar wsConnected={true} modelConfigured={true} />);
    expect(screen.queryByText('claude-sonnet-4-6')).toBeNull();
    // 连接标识仍在
    expect(screen.getByText('online')).toBeInTheDocument();
    expect(screen.getByText('local')).toBeInTheDocument();
  });
});
