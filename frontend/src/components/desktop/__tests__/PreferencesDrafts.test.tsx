/**
 * PreferencesModal 草稿 tab — 列出 localStorage 中所有 nexus-draft-* 草稿,提供跳回 / 删除。
 *
 * 第十三轮(2026-07-24):让用户能从偏好弹窗看到所有 project 的草稿,
 * 一键跳回(切 active project + 关闭弹窗)或删除草稿。
 *
 * 测试模式:
 *   - fireEvent 而非 userEvent(项目无 @testing-library/user-event)
 *   - vi.mock store 注入 projects 列表
 *   - 跳回路径:跳回项目后由父 modal 接 closeModal;setActiveProject 是 async,需 fireEvent 后等 microtask
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { PreferencesModal } from '../PreferencesModal';

const storeState = {
  // 既有 PreferencesModal 依赖的字段(其它测试覆盖)
  activeProjectId: 'default',
  showThinking: false,
  setShowThinking: vi.fn(),
  darkMode: false,
  toggleDarkMode: vi.fn(),
  fontScale: 1 as 0.875 | 1 | 1.25,
  setFontScale: vi.fn(),
  models: [],
  currentModelId: '',
  // Drafts tab 新增依赖
  projects: [
    { id: 'default', name: '默认项目', path: '~/.nexus/projects/default', created_at: '2026-07-01' },
    { id: 'p2', name: '项目 B', path: '~/.nexus/projects/p2', created_at: '2026-07-02' },
  ],
  setActiveProject: vi.fn(() => Promise.resolve()),
};

vi.mock('../../../store', () => ({
  useStore: (sel?: (s: typeof storeState) => unknown) => (sel ? sel(storeState) : storeState),
  getState: () => storeState,
}));

const writeDraft = (projectId: string, text: string, savedAt?: number): void => {
  localStorage.setItem(
    `nexus-draft-${projectId}`,
    JSON.stringify({ text, savedAt: savedAt ?? Date.now() }),
  );
};

/** 草稿 tab 调 useNavigate(react-router v7),测试需套 MemoryRouter 提供上下文 */
const renderModal = (ui: React.ReactElement): ReturnType<typeof render> =>
  render(
    <MemoryRouter initialEntries={['/chat']}>
      {ui}
    </MemoryRouter>,
  );

// jsdom 在 vitest 模式下不暴露 localStorage(v4.1.10 + experimental 警告),
// 手写 mock storage 替代,只暴露本测试用到的 3 个 API。
interface MockStorage {
  data: Map<string, string>;
  getItem: (k: string) => string | null;
  setItem: (k: string, v: string) => void;
  removeItem: (k: string) => void;
  clear: () => void;
  key: (i: number) => string | null;
  get length(): number;
}
function makeMockStorage(): MockStorage {
  const data = new Map<string, string>();
  return {
    data,
    getItem: (k) => (data.has(k) ? data.get(k)! : null),
    setItem: (k, v) => data.set(k, v),
    removeItem: (k) => data.delete(k),
    clear: () => data.clear(),
    key: (i) => Array.from(data.keys())[i] ?? null,
    get length() {
      return data.size;
    },
  };
}

let originalLocalStorage: Storage | undefined;

describe('PreferencesModal 草稿 tab', () => {
  beforeEach(() => {
    const mock = makeMockStorage();
    originalLocalStorage = globalThis.localStorage;
    Object.defineProperty(window, 'localStorage', {
      value: mock,
      configurable: true,
      writable: true,
    });
    localStorage.clear();
    storeState.setActiveProject.mockClear();
  });

  afterEach(() => {
    Object.defineProperty(window, 'localStorage', {
      value: originalLocalStorage,
      configurable: true,
      writable: true,
    });
  });

  it('切到草稿 tab → 列出 localStorage 已存的草稿(项目名 + 预览 + 跳回/删除)', () => {
    writeDraft('default', '一段草稿内容');
    renderModal(<PreferencesModal open onClose={() => {}} />);

    // 切到草稿 tab
    fireEvent.click(screen.getByRole('tab', { name: '草稿' }));

    // 项目名 + 预览
    expect(screen.getByText('默认项目')).toBeInTheDocument();
    expect(screen.getByText(/一段草稿内容/)).toBeInTheDocument();
    // 跳回 / 删除 按钮存在
    expect(screen.getByRole('button', { name: '跳回' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '删除' })).toBeInTheDocument();
  });

  it('点删除 → localStorage 条目被清掉,UI 重扫为空', () => {
    writeDraft('default', '一段草稿内容');
    renderModal(<PreferencesModal open onClose={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: '草稿' }));

    expect(localStorage.getItem('nexus-draft-default')).not.toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '删除' }));

    expect(localStorage.getItem('nexus-draft-default')).toBeNull();
    expect(screen.getByText('暂无草稿')).toBeInTheDocument();
  });

  it('空状态显示"暂无草稿"', () => {
    renderModal(<PreferencesModal open onClose={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: '草稿' }));

    expect(screen.getByText('暂无草稿')).toBeInTheDocument();
  });

  it('nexus-draft-_none 被过滤掉(只列真实 project)', () => {
    localStorage.setItem(
      'nexus-draft-_none',
      JSON.stringify({ text: '兜底草稿', savedAt: Date.now() }),
    );
    writeDraft('default', '真实草稿');
    renderModal(<PreferencesModal open onClose={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: '草稿' }));

    // 真实草稿在
    expect(screen.getByText(/真实草稿/)).toBeInTheDocument();
    // 兜底草稿不在
    expect(screen.queryByText(/兜底草稿/)).not.toBeInTheDocument();
  });

  it('点跳回 → setActiveProject 被调用 + 弹窗关闭', async () => {
    const onClose = vi.fn();
    writeDraft('p2', 'P2 草稿');
    renderModal(<PreferencesModal open onClose={onClose} />);
    fireEvent.click(screen.getByRole('tab', { name: '草稿' }));

    fireEvent.click(screen.getByRole('button', { name: '跳回' }));

    await waitFor(() => {
      expect(storeState.setActiveProject).toHaveBeenCalledWith('p2');
    });
    expect(onClose).toHaveBeenCalled();
  });
});
