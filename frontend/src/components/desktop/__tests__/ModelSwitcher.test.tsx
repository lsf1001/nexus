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
 *   - 点列表项 → 调 store.setModelName + 收起
 *   - 拉 API 失败 → 不渲染 dropdown(降级),保留 chip
 *   - 外部 click → 收起(dropdown 自动 close)
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { ModelSwitcher } from '../ModelSwitcher';
import { useStore } from '../../../store';

function setStoreModelList(models: Array<{ id: string; name: string; api_key: string; api_base: string; temperature: number; is_active: boolean }>) {
  useStore.setState({
    models,
    modelName: models.find((m) => m.is_active)?.name ?? models[0]?.name ?? '',
  });
}

describe('ModelSwitcher (第九轮)', () => {
  beforeEach(() => {
    // 重置 store 单测专用字段
    useStore.setState({ models: [], modelName: '' });
    vi.restoreAllMocks();
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

  it('点列表项 → 调 useStore.setModelName 切到新模型', () => {
    setStoreModelList([
      { id: 'm1', name: 'GPT-4o', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'Claude-Sonnet', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);
    expect(useStore.getState().modelName).toBe('Claude-Sonnet');
  });

  it('点列表项后 dropdown 自动收起', () => {
    setStoreModelList([
      { id: 'm1', name: 'A', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: true },
      { id: 'm2', name: 'B', api_key: 'k', api_base: 'https://api', temperature: 0.7, is_active: false },
    ]);
    const { container } = render(<ModelSwitcher />);
    fireEvent.click(container.querySelector('.model-switcher-chip') as HTMLElement);
    const second = container.querySelectorAll('.model-switcher-item')[1] as HTMLElement;
    fireEvent.click(second);
    expect(container.querySelector('.model-switcher-dropdown')).toBeNull();
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
