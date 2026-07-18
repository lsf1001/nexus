/**
 * Task 3.3 单测 — artifact 内容识别 + artifacts slice 去重。
 *
 * WHY:final / tool_result 帧的 content 可能携带 `<!-- artifact ... -->`
 * 结构化标记(向后兼容新增,不改 WS 协议)。wsHandlers.extractArtifact 纯函数
 * 负责识别,store 的 pushArtifact 按 id 去重。
 *
 * 覆盖:
 *   1. extractArtifact 命中各 kind(code/markdown/svg/html),含可选 lang/title。
 *   2. 无标记 → null;kind 非法 → null(零副作用)。
 *   3. pushArtifact 同 id 去重(只留一条);clearArtifacts 清空。
 */
import { describe, expect, it } from 'vitest';
import { create } from 'zustand';
import { extractArtifact } from '../wsHandlers';
import {
  createArtifactsSlice,
  type ArtifactsSlice,
} from '../../../../store/slices/artifacts';

function makeArtifactsStore() {
  return create<ArtifactsSlice>()((...a) => createArtifactsSlice(...a));
}

const CODE = `<!-- artifact kind=code lang=ts title=MyScript -->
const x = 1;
<!-- /artifact -->`;

const MARKDOWN = `<!-- artifact kind=markdown title=Notes -->
# Title
body **bold**
<!-- /artifact -->`;

const SVG = `<!-- artifact kind=svg title=Chart -->
<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>
<!-- /artifact -->`;

const HTML = `<!-- artifact kind=html title=Widget -->
<div>hello</div>
<!-- /artifact -->`;

describe('extractArtifact', () => {
  it('code kind → 正确 Artifact(含 lang/title)', () => {
    const a = extractArtifact(CODE);
    expect(a).not.toBeNull();
    expect(a!.kind).toBe('code');
    expect(a!.language).toBe('ts');
    expect(a!.title).toBe('MyScript');
    expect(a!.content).toBe('const x = 1;');
    expect(a!.id).toBeTruthy();
  });

  it('markdown kind → 正确 Artifact(content 含多行)', () => {
    const a = extractArtifact(MARKDOWN);
    expect(a).not.toBeNull();
    expect(a!.kind).toBe('markdown');
    expect(a!.title).toBe('Notes');
    expect(a!.content).toBe('# Title\nbody **bold**');
  });

  it('svg kind → 正确 Artifact', () => {
    const a = extractArtifact(SVG);
    expect(a).not.toBeNull();
    expect(a!.kind).toBe('svg');
    expect(a!.title).toBe('Chart');
    expect(a!.content).toContain('<svg');
  });

  it('html kind → 正确 Artifact', () => {
    const a = extractArtifact(HTML);
    expect(a).not.toBeNull();
    expect(a!.kind).toBe('html');
    expect(a!.title).toBe('Widget');
    expect(a!.content).toContain('<div>hello</div>');
  });

  it('无 artifact 标记 → 返回 null(零副作用)', () => {
    expect(extractArtifact('普通消息内容,没有任何标记')).toBeNull();
    expect(extractArtifact('')).toBeNull();
  });

  it('kind 非法 → 返回 null', () => {
    expect(
      extractArtifact('<!-- artifact kind=pdf -->x<!-- /artifact -->'),
    ).toBeNull();
  });

  it('属性值可带引号', () => {
    const a = extractArtifact(
      `<!-- artifact kind=code lang="ts" title="My Script" -->
x
<!-- /artifact -->`,
    );
    expect(a).not.toBeNull();
    expect(a!.language).toBe('ts');
    expect(a!.title).toBe('My Script');
  });
});

describe('artifacts slice', () => {
  it('pushArtifact 同 id 去重(只留一条)', () => {
    const store = makeArtifactsStore();
    store.getState().pushArtifact({ id: 'a', kind: 'code', content: 'x' });
    store.getState().pushArtifact({ id: 'a', kind: 'code', content: 'y' });
    store.getState().pushArtifact({ id: 'b', kind: 'markdown', content: 'z' });
    const arts = store.getState().artifacts;
    expect(arts).toHaveLength(2);
    // 重复 id 保留首条,不被覆盖
    expect(arts.find((a) => a.id === 'a')?.content).toBe('x');
    expect(arts.some((a) => a.id === 'b')).toBe(true);
  });

  it('clearArtifacts 清空全部', () => {
    const store = makeArtifactsStore();
    store.getState().pushArtifact({ id: 'a', kind: 'code', content: 'x' });
    expect(store.getState().artifacts).toHaveLength(1);
    store.getState().clearArtifacts();
    expect(store.getState().artifacts).toHaveLength(0);
  });
});
