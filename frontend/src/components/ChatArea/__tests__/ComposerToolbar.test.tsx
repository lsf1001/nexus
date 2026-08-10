/**
 * ComposerToolbar 风格选择器测试 — Round 6.1 Task 9。
 *
 * 覆盖:
 * 1. trigger 默认显示 "默认"
 * 2. 点 trigger → 菜单展开,选 '专业' → store.sessionStyles[sid] = 'professional'
 *    + 触发 apiPatch
 * 3. PATCH 失败 → store 回滚 + console.error
 * 4. trigger 旁显示风格徽标(非 default 时)
 *
 * sessionId 由父级 Composer 通过 prop 注入(与 conversationId 链路对齐),
 * store 不引入 activeSessionId 字段(避免无业务收益的全局态)。
 *
 * Radix DropdownMenu 的菜单项只在 trigger click 后才挂到 DOM,
 * 测试通过 fireEvent.click(trigger) 打开菜单后再 fireEvent.click(item) 操作。
 */
import type { JSX } from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ComposerToolbar } from '../ComposerToolbar';
import { useStore } from '../../../store';
import { apiPatch } from '../../../lib/api';

/** TooltipProvider 包一层:ComposerToolbar 内部 Tooltip 依赖 Radix context */
function ToolbarWithProvider(props: { sessionId: string }): JSX.Element {
  return (
    <TooltipProvider>
      <ComposerToolbar {...props} />
    </TooltipProvider>
  );
}

vi.mock('../../../lib/api', async (importOriginal) => {
  const mod = await importOriginal<typeof import('../../../lib/api')>();
  return { ...mod, apiPatch: vi.fn() };
});

const SID = 'test-session-1';

/** 打开 Radix DropdownMenu:点击 trigger 后等待 menu item 出现
 *  Radix DropdownMenu 的 Trigger 用 pointerdown 响应(非 click),
 *  fireEvent.click 在 jsdom 里触发不到内部 onPointerDown 监听,
 *  用 fireEvent.pointerDown 模拟真实指针事件序列 */
async function openStyleMenu(): Promise<void> {
  const trigger = screen.getByLabelText('选择回复风格');
  fireEvent.pointerDown(trigger, { button: 0, pointerType: 'mouse' });
  fireEvent.click(trigger);
  await waitFor(() => {
    expect(screen.getByRole('menuitem', { name: '专业' })).toBeInTheDocument();
  });
}

describe('ComposerToolbar 风格选择器', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useStore.setState({ sessionStyles: {} });
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('trigger 默认显示 "默认"', () => {
    render(<ToolbarWithProvider sessionId={SID} />);
    expect(screen.getByLabelText('选择回复风格')).toHaveTextContent('默认');
  });

  it('打开菜单 → 点专业 → store 更新 + apiPatch', async () => {
    (apiPatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      style: 'professional',
    });
    render(<ToolbarWithProvider sessionId={SID} />);
    await openStyleMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: '专业' }));
    await waitFor(() => {
      expect(useStore.getState().sessionStyles[SID]).toBe('professional');
    });
    expect(apiPatch).toHaveBeenCalledWith(`/api/sessions/${SID}`, {
      style: 'professional',
    });
  });

  it('PATCH 失败 → store 回滚 + console.error', async () => {
    // 先成功切到 professional
    (apiPatch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      style: 'professional',
    });
    const { rerender } = render(<ToolbarWithProvider sessionId={SID} />);
    await openStyleMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: '专业' }));
    await waitFor(() => {
      expect(useStore.getState().sessionStyles[SID]).toBe('professional');
    });

    // 第二次切换,这次 PATCH 失败
    (apiPatch as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error('500: boom'),
    );
    rerender(<ToolbarWithProvider sessionId={SID} />);
    await openStyleMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: '默认' }));
    await waitFor(() => {
      expect(useStore.getState().sessionStyles[SID]).toBe('default');
    });
    expect(console.error).toHaveBeenCalled();
  });

  it('trigger 旁显示风格徽标(非 default 时)', async () => {
    (apiPatch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      style: 'concise',
    });
    render(<ToolbarWithProvider sessionId={SID} />);
    await openStyleMenu();
    fireEvent.click(screen.getByRole('menuitem', { name: '简洁' }));
    await waitFor(() => {
      expect(useStore.getState().sessionStyles[SID]).toBe('concise');
    });
    // 徽标 .style-badge 文本等于当前 label
    expect(document.querySelector('.style-badge')?.textContent).toBe('简洁');
  });

  it('default 风格时不显示徽标', () => {
    render(<ToolbarWithProvider sessionId={SID} />);
    expect(document.querySelector('.style-badge')).toBeNull();
  });
});