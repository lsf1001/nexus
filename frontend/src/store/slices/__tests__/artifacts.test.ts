import { describe, it, expect, beforeEach } from 'vitest';
import { useStore } from '../../index';
import type { Artifact } from '../artifacts';

function makeArtifact(overrides: Partial<Artifact> = {}): Artifact {
  return {
    id: 'a1',
    kind: 'code',
    content: 'print("hi")',
    language: 'python',
    createdAt: Date.now(),
    ...overrides,
  };
}

/** 跑单个 action + 读最新 store 状态的 helper */
function act<T>(fn: () => T): T {
  return fn();
}

describe('artifacts slice', () => {
  beforeEach(() => {
    // 每个用例前重置
    act(() => {
      useStore.getState().clearArtifacts();
      useStore.getState().setArtifactsCollapsed(true);
      useStore.getState().setActiveArtifact(null);
    });
  });

  describe('pushArtifact', () => {
    it('追加新 artifact 并自动激活 + 展开', () => {
      const a = makeArtifact({ id: 'a1' });
      useStore.getState().pushArtifact(a);

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(1);
      expect(s.artifacts[0]?.id).toBe('a1');
      expect(s.activeArtifactId).toBe('a1');
      expect(s.artifactsCollapsed).toBe(false);
    });

    it('重复 id 忽略(去重)', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1', content: 'first' }));
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1', content: 'second' }));

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(1);
      expect(s.artifacts[0]?.content).toBe('first');
    });

    it('追加第二个不同 id 的 artifact 切换 active 到最新', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().pushArtifact(makeArtifact({ id: 'a2' }));

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(2);
      expect(s.activeArtifactId).toBe('a2');
    });
  });

  describe('clearArtifacts', () => {
    it('清空 list 与 activeId(不影响 collapsed)', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().setArtifactsCollapsed(false);
      useStore.getState().clearArtifacts();

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(0);
      expect(s.activeArtifactId).toBeNull();
      // collapsed 是 UI 偏好维度,不清 — 让用户面板状态稳定
      expect(s.artifactsCollapsed).toBe(false);
    });
  });

  describe('setActiveArtifact', () => {
    it('切换 active 不改 list', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().pushArtifact(makeArtifact({ id: 'a2' }));
      useStore.getState().setActiveArtifact('a1');

      expect(useStore.getState().activeArtifactId).toBe('a1');
      expect(useStore.getState().artifacts).toHaveLength(2);
    });

    it('可置 null(回到空态)', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().setActiveArtifact(null);
      expect(useStore.getState().activeArtifactId).toBeNull();
    });
  });

  describe('removeArtifact', () => {
    it('删除非 active 不动 activeId', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().pushArtifact(makeArtifact({ id: 'a2' }));
      useStore.getState().setActiveArtifact('a1');
      useStore.getState().removeArtifact('a2');

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(1);
      expect(s.activeArtifactId).toBe('a1');
    });

    it('删除 active 时 activeId 置 null', () => {
      useStore.getState().pushArtifact(makeArtifact({ id: 'a1' }));
      useStore.getState().removeArtifact('a1');

      const s = useStore.getState();
      expect(s.artifacts).toHaveLength(0);
      expect(s.activeArtifactId).toBeNull();
    });
  });

  describe('toggleArtifactsCollapsed', () => {
    it('true ↔ false 翻转', () => {
      const before = useStore.getState().artifactsCollapsed;
      useStore.getState().toggleArtifactsCollapsed();
      expect(useStore.getState().artifactsCollapsed).toBe(!before);
    });
  });

  describe('setArtifactsCollapsed', () => {
    it('显式设值', () => {
      useStore.getState().setArtifactsCollapsed(false);
      expect(useStore.getState().artifactsCollapsed).toBe(false);
      useStore.getState().setArtifactsCollapsed(true);
      expect(useStore.getState().artifactsCollapsed).toBe(true);
    });
  });
});