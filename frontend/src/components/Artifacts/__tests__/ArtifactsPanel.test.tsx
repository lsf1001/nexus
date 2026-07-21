import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ArtifactsPanel } from '../ArtifactsPanel';
import { useStore } from '../../../store';
import type { Artifact } from '../../../store/slices/artifacts';

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'a1',
    kind: 'code',
    content: 'print("hi")',
    language: 'python',
    filename: 'hello.py',
    createdAt: Date.now(),
    ...overrides,
  };
}

describe('ArtifactsPanel', () => {
  beforeEach(() => {
    useStore.getState().clearArtifacts();
    useStore.getState().setArtifactsCollapsed(false);
  });

  it('折叠态不渲染', () => {
    useStore.getState().setArtifactsCollapsed(true);
    const { container } = render(<ArtifactsPanel />);
    expect(container.querySelector('.artifacts-panel')).toBeNull();
  });

  it('展开 + 空列表 → 空态', () => {
    const { container } = render(<ArtifactsPanel />);
    expect(container.querySelector('.artifacts-empty')).toBeTruthy();
    expect(screen.getByText('还没有产物')).toBeTruthy();
  });

  it('展开 + 有产物 → head + tabs + body + foot', () => {
    useStore.getState().pushArtifact(makeArtifact({ id: 'a1', kind: 'code', language: 'python', filename: 'q.py' }));
    const { container } = render(<ArtifactsPanel />);
    expect(container.querySelector('.artifact-head')).toBeTruthy();
    expect(container.querySelector('.artifact-tabs')).toBeTruthy();
    expect(container.querySelector('.artifact-body')).toBeTruthy();
    expect(container.querySelector('.artifact-foot')).toBeTruthy();
    expect(container.querySelector('.artifact-renderer-code')).toBeTruthy();
  });

  it('多个 artifact 时显示 N/N 计数(active 是最后 push 的)', () => {
    useStore.getState().pushArtifact(makeArtifact({ id: 'a1', filename: 'a.py' }));
    useStore.getState().pushArtifact(makeArtifact({ id: 'a2', filename: 'b.py' }));
    const { container } = render(<ArtifactsPanel />);
    expect(container.querySelector('.artifact-counter')?.textContent).toBe('2 / 2');
  });

  it('切换 active 后计数更新', () => {
    useStore.getState().pushArtifact(makeArtifact({ id: 'a1', filename: 'a.py' }));
    useStore.getState().pushArtifact(makeArtifact({ id: 'a2', filename: 'b.py' }));
    useStore.getState().setActiveArtifact('a1');
    const { container } = render(<ArtifactsPanel />);
    expect(container.querySelector('.artifact-counter')?.textContent).toBe('1 / 2');
  });

  it('close 按钮触发 setCollapsed(true)', () => {
    useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
    const { container } = render(<ArtifactsPanel />);
    container.querySelector<HTMLButtonElement>('.artifact-close')?.click();
    expect(useStore.getState().artifactsCollapsed).toBe(true);
  });

  it('tab 切换 active artifact(同 kind 多产物)', () => {
    useStore.getState().pushArtifact(makeArtifact({ id: 'a1', filename: 'a.py' }));
    useStore.getState().pushArtifact(makeArtifact({ id: 'a2', filename: 'b.py' }));
    // active 应是 a2(最后 push)
    expect(useStore.getState().activeArtifactId).toBe('a2');
    // Code tab 应该已 active
    const { container } = render(<ArtifactsPanel />);
    const codeTab = container.querySelector('.artifact-tab');
    expect(codeTab?.classList.contains('is-active')).toBe(true);
    expect(codeTab?.textContent).toContain('Code');
  });
});