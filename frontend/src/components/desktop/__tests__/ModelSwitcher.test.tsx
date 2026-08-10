/**
 * ModelSwitcher 单测 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Claude Desktop / ChatGPT 把模型切换放在顶栏右侧,一键 dropdown,
 * 切完即用,不藏到设置页。第九轮新增 ModelSwitcher,token 同 store
 * `modelName` + `setModelName`,跟 ModelConfigModal 数据源一致。
 *
 * 契约:
 *   - 默认收起,chip 显示当前 model 名 + ▾
 *   - 点 chip → 展开 dropdown 列表
 *   - 列表项:已选 = 加粗 + 绿点(.is-active)
 *   - 点列表项 → 调 switchModel(id);成功后 store.setModelName + 收起 + toast.success
 *   - switchModel 进行中 → chip 显示"切换中…",列表项 disabled
 *   - switchModel 失败 → 保留原 modelName + dropdown 收起 + toast.error
 *   - 拉 API 失败 → 不渲染 dropdown(降级),保留 chip
 *   - 外部 click → 收起(dropdown 自动 close)
 *
 * WHY vi.mock factory:ModelSwitcher 用 named import `{ switchModel }` 绑在
 * import 期;`vi.spyOn` 改 apiLib 命名空间但**改不到已绑定的引用**。
 * 用 factory + 共享 `switchModelMock = vi.fn()` 才能拦截调用并控制 resolve/reject。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { ModelSwitcher } from '../ModelSwitcher';
import { useStore } from '../../../store';
import { useToastStore } from '../../../store/useToast';

const switchModelMock = vi.fn();
vi.mock('../../../lib/api', () => ({
  switchModel: (...args: unknown[]) => switchModelMock(...args),
}));

function setStoreModelList(models: Array<{ id: string; name: string; api_key: string; api_base: string; temperature: number; is_active: boolean }>) {
  useStore.setState({
    models,
    modelName: models.find((m) => m.is_active)?.name ?? models[0]?.name ?? '',
  });
}

function clearToasts(): void {
  useToastStore.setState({ toasts: [] });
}

describe('ModelSwitcher (第九轮)', () => {
  beforeEach(() => {
    // 重置 store 单测专用字段
    useStore.setState({ models: [], modelName: '' });
    switchModelMock.mockReset();
    switchModelMock.mockResolvedValue(undefined);
    clearToasts();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('无模型列表时只渲染 chip 占位(不渲染 dropdown)', () => {
    const { container } = render(<ModelSwitcher />);
    const chip = container.querySelector('.model-switcher-chip');
    expect(chip).not.toBeNull();
    // dropdown 节点不应挂载
    expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
  });

  it('当前 modelName 渲染在 chip 上', () => {
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
    ]);
    const { container } = render(<ModelSwitcher />);
    const chip = container.querySelector('.model-switcher-chip');
    expect(chip?.textContent).toContain('GPT-4o');
    expect(chip?.textContent).toContain('▾');
  });

  it('点 chip → 展开 dropdown,显示全部模型项', () => {
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    const chip = container.querySelector('.model-switcher-chip') as HTMLElement;
    fireEvent.click(chip);
    const dd = container.querySelector('.model-switcher-dropdown');
    expect(dd).not.toBeNull();
    const items = container.querySelectorAll('.model-switcher-item');
    expect(items.length).toBe(2);
    expect(items[0]?.textContent).toContain('GPT-4o');
    expect(items[1]?.textContent).toContain('Claude-Sonnet');
  });

  it('当前激活项加 .is-active 类', () => {
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const items = container.querySelectorAll('.model-switcher-item');
    expect(items[0]?.classList.contains('is-active')).toBe(true);
    expect(items[1]?.classList.contains('is-active')).toBe(false);
    // 激活项有绿点
    expect(container.querySelector('.model-switcher-item.is-active .model-switcher-dot')).not.toBeNull();
  });

  it('点列表项 → 调 switchModel(model.id);成功后切到新模型 + 收起 + toast', async () => {
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);

    await waitFor(() => {
      expect(switchModelMock).toHaveBeenCalledWith('m2');
    });
    await waitFor(() => {
      expect(useStore.getState().modelName).toBe('Claude-Sonnet');
    });
    await waitFor(() => {
      expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
    });
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.kind === 'success' && t.message.includes('Claude-Sonnet'))).toBe(true);
    });
  });

  it('switchModel 进行中 → chip 显示"切换中…",chip disabled', async () => {
    let resolveSwitch!: () => void;
    switchModelMock.mockImplementationOnce(
      () => new Promise<void>((resolve) => {
        resolveSwitch = resolve;
      }),
    );
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);

    // 进行中:chip 文本含"切换中…",dropdown 已收起(避免再次点击),chip 自身 aria-busy
    const chip = container.querySelector('.model-switcher-chip') as HTMLElement;
    await waitFor(() => {
      expect(chip.textContent).toContain('切换中');
      expect(chip.getAttribute('aria-busy')).toBe('true');
      expect(chip.hasAttribute('disabled')).toBe(true);
      // dropdown 已收起(setOpen(false) 在 setIsSwitching 之前)
      expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
    });

    // 完成:chip 恢复新模型名
    resolveSwitch();
    await waitFor(() => {
      expect(container.querySelector('.model-switcher-chip')?.textContent).toContain('Claude-Sonnet');
    });
  });

  it('switchModel 失败 → 保留原 modelName + dropdown 收起 + toast.error', async () => {
    switchModelMock.mockRejectedValueOnce(new Error('模型 Claude-Sonnet 未配置 API Key'));
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);

    await waitFor(() => {
      expect(switchModelMock).toHaveBeenCalledWith('m2');
    });
    // 回滚:modelName 不变
    expect(useStore.getState().modelName).toBe('GPT-4o');
    await waitFor(() => {
      expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
    });
    await waitFor(() => {
      const toasts = useToastStore.getState().toasts;
      expect(toasts.some((t) => t.kind === 'error' && t.message.includes('Claude-Sonnet'))).toBe(true);
      expect(toasts.some((t) => t.kind === 'error' && t.message.includes('GPT-4o'))).toBe(true);
    });
  });

  it('点列表项后 dropdown 自动收起(成功路径)', async () => {
    setStoreModelList([
      { id: 'm1', name: 'A', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'B', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);
    await waitFor(() => {
      expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
    });
  });

  it('再点 chip → 收起 dropdown', () => {
    setStoreModelList([
      { id: 'm1', name: 'A', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'B', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    const chip = container.querySelector('.model-switcher-chip') as HTMLElement;
    fireEvent.click(chip); // 展开
    fireEvent.click(chip); // 收起
    expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
  });
});