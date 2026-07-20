/**
 * 模拟人工测试 — 设置弹窗(只管理供应商配置 + 界面偏好 + 关于,2026-07-19)。
 *
 * 模拟一个真实用户的使用路径:
 *   1. 打开应用 → 左侧栏底部有"设置"按钮
 *   2. 点击"设置" → 弹出分区设置弹窗(PROVIDER + 界面 + 关于)
 *   3. 填写 Provider 信息 → 点"发现模型" → 预览可用模型列表
 *   4. 点"导入全部" → 模型自动添加到 store,输入框上方 ModelSelector 可切换
 *   5. 切换思考模式 / 深色模式 toggle
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { useState } from 'react';
import { Sidebar } from '../Sidebar';
import { PreferencesModal } from '../PreferencesModal';
import {
  refreshModelsIntoStore,
  discoverProviderModels,
  importProviderModels,
  deleteModel,
  switchModel,
} from '../../../lib/models';
import type { Conversation } from '../../../types';

const storeState = {
  showThinking: false,
  setShowThinking: vi.fn(),
  darkMode: false,
  toggleDarkMode: vi.fn(),
  starredIds: [] as string[],
  toggleStarred: vi.fn(),
  models: [
    { id: 'agnes-2.0-flash', name: 'agnes-2.0-flash', api_base: 'https://apihub.agnes-ai.com/v1', is_active: true },
    { id: 'agnes-1.5-flash', name: 'agnes-1.5-flash', api_base: 'https://apihub.agnes-ai.com/v1', is_active: false },
  ],
  currentModelId: 'agnes-2.0-flash',
};

// PreferencesModal 从 store 读 UI 偏好 + 模型列表。
vi.mock('../../../store', () => ({
  useStore: (sel?: (s: typeof storeState) => unknown) => (sel ? sel(storeState) : storeState),
  getState: () => storeState,
}));

// 网络操作 mock 成即时成功。
vi.mock('../../../lib/models', () => ({
  refreshModelsIntoStore: vi.fn(() => Promise.resolve([])),
  discoverProviderModels: vi.fn(() => Promise.resolve({
    ok: true,
    models: [
      { id: 'gpt-4o', name: 'gpt-4o', owned_by: 'openai' },
      { id: 'claude-sonnet-4', name: 'claude-sonnet-4', owned_by: 'anthropic' },
    ],
    count: 2,
  })),
  importProviderModels: vi.fn(() => Promise.resolve({
    ok: true,
    imported: ['gpt-4o', 'claude-sonnet-4'],
    count: 2,
  })),
  deleteModel: vi.fn(() => Promise.resolve({ ok: true })),
  switchModel: vi.fn(() => Promise.resolve({ ok: true })),
}));

function makeConv(id: string, title: string): Conversation {
  return { id, title, createdAt: new Date(), updatedAt: '2026-07-16T00:00:00Z', messages: [] };
}

function Harness() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Sidebar
        conversations={[makeConv('1', '示例对话')]}
        currentConversationId={null}
        onSelectConversation={vi.fn()}
        onDeleteConversation={vi.fn()}
        onNewTask={vi.fn()}
        onOpenPreferences={() => setOpen(true)}
      />
      <PreferencesModal open={open} onClose={() => setOpen(false)} />
    </>
  );
}

beforeEach(() => {
  vi.mocked(refreshModelsIntoStore).mockClear();
  vi.mocked(discoverProviderModels).mockClear();
  vi.mocked(importProviderModels).mockClear();
  vi.mocked(deleteModel).mockClear();
  vi.mocked(switchModel).mockClear();
  storeState.setShowThinking.mockClear();
  storeState.toggleDarkMode.mockClear();
});

describe('模拟人工:设置按钮入口', () => {
  it('左侧栏底部显示"设置"按钮', () => {
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
    const settingsBtn = screen.getByRole('button', { name: '设置' });
    expect(settingsBtn).not.toBeNull();
    expect(settingsBtn.textContent).toContain('设置');
    expect(container.querySelector('.account-trigger')).toBeNull();
    expect(screen.queryByText('退出登录')).toBeNull();
  });

  it('点击"设置" → onOpenPreferences 被调用', () => {
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

describe('模拟人工:设置弹窗界面偏好', () => {
  it('弹窗内有"显示思考过程"和"深色模式" toggle 按钮', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    // toggle 按钮在弹窗内,两个都是"已关闭"
    const toggles = within(dialog).getAllByRole('switch', { name: '已关闭' });
    expect(toggles.length).toBe(2);
  });

  it('点击"显示思考过程" toggle → setShowThinking', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    const toggles = within(dialog).getAllByRole('switch', { name: '已关闭' });
    fireEvent.click(toggles[0]!);
    expect(storeState.setShowThinking).toHaveBeenCalledWith(true);
  });

  it('点击"深色模式" toggle → toggleDarkMode', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    const toggles = within(dialog).getAllByRole('switch', { name: '已关闭' });
    fireEvent.click(toggles[1]!);
    expect(storeState.toggleDarkMode).toHaveBeenCalled();
  });
});

describe('模拟人工:Provider 模型发现', () => {
  it('弹窗包含 PROVIDER + 已导入模型 + 界面 + 关于四个分区', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    expect(within(dialog).getByText('PROVIDER')).not.toBeNull();
    expect(within(dialog).getByText('已导入模型')).not.toBeNull();
    expect(within(dialog).getByText('界面')).not.toBeNull();
    expect(within(dialog).getByText('关于')).not.toBeNull();
  });

  it('弹窗出现 Base URL + API Key 输入框 + 发现按钮', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    expect(within(dialog).getByLabelText('Base URL')).not.toBeNull();
    expect(within(dialog).getByLabelText('API Key')).not.toBeNull();
    expect(within(dialog).getByRole('button', { name: '发现模型' })).not.toBeNull();
  });

  it('点"发现模型" → 调 discoverProviderModels 并显示模型列表', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    // 填写 API Key(必填才能发现)
    fireEvent.change(within(dialog).getByLabelText('API Key'), { target: { value: 'sk-test-key' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '发现模型' }));

    await vi.waitFor(() => {
      expect(discoverProviderModels).toHaveBeenCalled();
    });

    // 发现后显示模型列表 + 导入按钮
    await vi.waitFor(() => {
      expect(within(dialog).getByText('gpt-4o')).not.toBeNull();
      expect(within(dialog).getByText('claude-sonnet-4')).not.toBeNull();
      expect(within(dialog).getByRole('button', { name: /导入全部/ })).not.toBeNull();
    });
  });

  it('点"导入全部" → 调 importProviderModels 并刷新 store', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    // 填写 API Key → 发现
    fireEvent.change(within(dialog).getByLabelText('API Key'), { target: { value: 'sk-test-key' } });
    fireEvent.click(within(dialog).getByRole('button', { name: '发现模型' }));
    await vi.waitFor(() => {
      expect(within(dialog).getByRole('button', { name: /导入全部/ })).not.toBeNull();
    });

    // 再导入
    fireEvent.click(within(dialog).getByRole('button', { name: /导入全部/ }));
    await vi.waitFor(() => {
      expect(importProviderModels).toHaveBeenCalled();
      expect(refreshModelsIntoStore).toHaveBeenCalled();
    });
  });

  it('点关闭(X)→ 弹窗消失', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    expect(screen.getByRole('dialog', { name: '设置' })).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '关闭设置' }));
    expect(screen.queryByRole('dialog', { name: '设置' })).toBeNull();
  });
});

describe('模拟人工:模型管理', () => {
  it('弹窗显示已导入的模型列表', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    expect(within(dialog).getByText('agnes-2.0-flash')).not.toBeNull();
    expect(within(dialog).getByText('agnes-1.5-flash')).not.toBeNull();
    expect(within(dialog).getByText('激活')).not.toBeNull();
  });

  it('点击非激活模型 → switchModel', async () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    // 点击 agnes-1.5-flash(非激活)的主区域
    const btn = within(dialog).getByTitle('点击切换到此模型');
    fireEvent.click(btn);
    await vi.waitFor(() => {
      expect(switchModel).toHaveBeenCalledWith('agnes-1.5-flash');
    });
  });

  it('点击删除按钮 → 确认后调 deleteModel', async () => {
    // mock confirm 返回 true
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '设置' }));
    const dialog = screen.getByRole('dialog', { name: '设置' });

    const deleteBtn = within(dialog).getByLabelText('删除 agnes-1.5-flash');
    fireEvent.click(deleteBtn);
    await vi.waitFor(() => {
      expect(deleteModel).toHaveBeenCalledWith('agnes-1.5-flash');
    });
    vi.restoreAllMocks();
  });
});
