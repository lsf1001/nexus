/**
 * 模拟人工测试 — 设置入口 + 模型配置全流程(2026-07-18)。
 *
 * 模拟一个真实用户的使用路径:
 *   1. 打开应用 → 看到左侧栏底部直接有"设置"文字按钮(不再是 N 头像下拉)
 *   2. 点击"设置" → 弹出设置弹窗
 *   3. 弹窗内含"模型配置"区块:模型 / API 地址 / API 密钥 / 温度参数 + 保存按钮
 *   4. 用户修改模型名 → 点"保存配置" → 调用 PUT /api/models/default
 *   5. 界面偏好区有"显示思考过程""深色模式"两个开关
 *
 * 用最小 harness 把 Sidebar 与 PreferencesModal 串成闭环,等价于真人点击。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { Sidebar } from '../Sidebar';
import { PreferencesModal } from '../PreferencesModal';
import { apiFetch } from '../../../lib/api';
import type { Conversation } from '../../../types';

vi.mock('../../../store', () => ({
  useStore: () => ({
    showThinking: false,
    setShowThinking: vi.fn(),
    darkMode: false,
    toggleDarkMode: vi.fn(),
  }),
}));

vi.mock('../../../lib/api', () => ({
  apiFetch: vi.fn(() =>
    Promise.resolve({
      ok: true,
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    }),
  ),
}));

function makeConv(id: string, title: string): Conversation {
  return { id, title, createdAt: new Date(), updatedAt: '2026-07-16T00:00:00Z', messages: [] };
}

function Harness({ onOpenSpy }: { onOpenSpy?: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Sidebar
        conversations={[makeConv('1', '示例对话')]}
        currentConversationId={null}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onNewTask={vi.fn()}
        onOpenPreferences={() => {
          onOpenSpy?.();
          setOpen(true);
        }}
      />
      <PreferencesModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}

beforeEach(() => {
  vi.mocked(apiFetch).mockClear();
});

describe('模拟人工:设置按钮入口', () => {
  it('左侧栏底部直接显示"设置"文字按钮(无 N 头像下拉)', () => {
    const { container } = render(
      <Sidebar
        conversations={[]}
        currentConversationId={null}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onNewTask={vi.fn()}
        onOpenPreferences={vi.fn()}
      />,
    );
    // 直接能看到"设置"按钮
    const settingsBtn = screen.getByRole('button', { name: '设置' });
    expect(settingsBtn).not.toBeNull();
    expect(settingsBtn.textContent).toContain('设置');
    // N 头像下拉触发器不应存在
    expect(container.querySelector('.account-trigger')).toBeNull();
    expect(screen.queryByText('退出登录')).toBeNull();
  });

  it('点击"设置" → onOpenPreferences 被调用(模拟用户打开设置)', () => {
    const spy = vi.fn();
    render(
      <Sidebar
        conversations={[]}
        currentConversationId={null}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onNewTask={vi.fn()}
        onOpenPreferences={spy}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe('模拟人工:设置弹窗含模型配置', () => {
  it('点击"设置"后弹窗出现,含"模型配置"全部字段', () => {
    render(<Harness />);
    // 弹窗此时未打开
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull();

    // 模拟真人点击设置
    fireEvent.click(screen.getByRole('button', { name: '设置' }));

    const dialog = screen.getByRole('dialog', { name: '设置' });
    expect(dialog).not.toBeNull();

    // 标题
    expect(within(dialog).getByText('设置')).not.toBeNull();

    // 模型配置区块
    expect(within(dialog).getByText('模型配置')).not.toBeNull();

    // 四个输入字段标签
    expect(within(dialog).getByLabelText('模型')).not.toBeNull();
    expect(within(dialog).getByLabelText('API 地址')).not.toBeNull();
    expect(within(dialog).getByLabelText('API 密钥')).not.toBeNull();
    expect(within(dialog).getByLabelText('温度参数')).not.toBeNull();

    // 保存按钮
    expect(within(dialog).getByRole('button', { name: '保存配置' })).not.toBeNull();

    // 界面偏好开关
    expect(within(dialog).getByLabelText('显示思考过程')).not.toBeNull();
    expect(within(dialog).getByLabelText('深色模式')).not.toBeNull();
  });

  it('模型名输入框默认有值(来自后端或默认值)', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const modelInput = screen.getByLabelText('模型') as HTMLInputElement;
    expect(modelInput.value.length).toBeGreaterThan(0);
  });

  it('修改模型名并点保存 → 调用 PUT /api/models/default 带上新值', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));

    const modelInput = screen.getByLabelText('模型') as HTMLInputElement;
    fireEvent.change(modelInput, { target: { value: 'gpt-4o-mini-测试' } });

    fireEvent.click(screen.getByRole('button', { name: '保存配置' }));

    // 等待异步保存
    await screen.findByText('已保存', undefined, { timeout: 2000 });

    expect(apiFetch).toHaveBeenCalledWith(
      '/api/models/default',
      expect.objectContaining({
        method: 'PUT',
        body: expect.stringContaining('gpt-4o-mini-测试'),
      }),
    );
  });

  it('点关闭(X)→ 弹窗消失', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    expect(screen.getByRole('dialog', { name: '设置' })).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }));
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull();
  });
});
