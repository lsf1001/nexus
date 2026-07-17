import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SHELL_CSS = readFileSync(join(HERE, '..', 'shell.css'), 'utf-8');

describe('task-item 当前态 3px 竖条视觉锁', () => {
  it('::before 伪元素有 position + width 3px + 初始透明', () => {
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*position:\s*absolute/);
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*width:\s*3px/);
    expect(SHELL_CSS).toMatch(/\.task-item::before\s*\{[^}]*background:\s*transparent/);
  });

  it('is-current 状态 ::before 背景色为 --ink', () => {
    expect(SHELL_CSS).toMatch(/\.task-item\.is-current::before\s*\{[^}]*background:\s*var\(--ink\)/);
  });

  it('task-item 不能再用填充色做当前态(防回归)', () => {
    expect(SHELL_CSS).not.toMatch(/\.task-item\.is-current\s*\{[^}]*background-color/);
  });
});
