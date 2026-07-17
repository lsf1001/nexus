/**
 * tokens.css 间距/字号 token 锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:第八轮只定了颜色 token,缺间距和字号 token,导致 shell.css / chat.css
 * 里散落硬编码的 px(8px / 16px / 20px 等)。第九轮补齐 `--space-1..7` 和
 * `--font-xs..2xl`,组件 CSS 渐进替换硬编码。
 *
 * 锁住契约:这些 token 必须存在 + 值在合理区间(间距 4-48,字号 12-36)。
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

// Task 1.2:tokens.css 已并入 index.css,测试改读 index.css 的 token 块。
const TOKENS_PATH = join(
  __dirname,
  '..',
  '..',
  'index.css',
);

function readTokens(): string {
  return readFileSync(TOKENS_PATH, 'utf-8');
}

function getTokenValue(css: string, name: string): string {
  // 匹配 `:root { ... --name: VALUE; ... }` 里紧贴 :root 的第一个声明;
  // 这里不区分 light/dark — 我们只关心 :root 块里有这些 token。
  const re = new RegExp(`--${name}:\\s*([0-9.]+)px\\s*;`);
  const m = css.match(re);
  if (!m) throw new Error(`未找到 --${name}: VALUEpx;`);
  return m[1]!;
}

describe('tokens.css 间距 token (--space-1..7)', () => {
  const css = readTokens();
  const SPACE = {
    'space-1': 4,
    'space-2': 8,
    'space-3': 12,
    'space-4': 16,
    'space-5': 24,
    'space-6': 32,
    'space-7': 48,
  };
  for (const [name, expected] of Object.entries(SPACE)) {
    it(`--${name} 必须存在且 = ${expected}px`, () => {
      const v = parseFloat(getTokenValue(css, name));
      expect(v).toBe(expected);
    });
  }

  it('间距必须单调递增', () => {
    const values = Object.values(SPACE);
    for (let i = 1; i < values.length; i++) {
      const prev = values[i - 1]!;
      const cur = values[i]!;
      expect(cur, `space-${i + 1}(${cur}) 必须 > space-${i}(${prev})`).toBeGreaterThan(prev);
    }
  });
});

describe('tokens.css 字号 token (--font-xs..2xl)', () => {
  const css = readTokens();
  const FONT = {
    'font-xs': 12,
    'font-sm': 13,
    'font-base': 14,
    'font-md': 16,
    'font-lg': 20,
    'font-xl': 28,
    'font-2xl': 36,
  };
  for (const [name, expected] of Object.entries(FONT)) {
    it(`--${name} 必须存在且 = ${expected}px`, () => {
      const v = parseFloat(getTokenValue(css, name));
      expect(v).toBe(expected);
    });
  }

  it('字号必须单调递增', () => {
    const values = Object.values(FONT);
    for (let i = 1; i < values.length; i++) {
      const prev = values[i - 1]!;
      const cur = values[i]!;
      expect(cur, `font-${i + 1}(${cur}) 必须 > font-${i}(${prev})`).toBeGreaterThan(prev);
    }
  });
});