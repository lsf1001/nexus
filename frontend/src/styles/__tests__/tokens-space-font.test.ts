/**
 * tokens.css 间距/字号 token 锁测试 — 2026-07-16 第九轮 UI 重设计 + 2026-07-21 字号重塑。
 *
 * WHY:第八轮只定了颜色 token,缺间距和字号 token,导致 shell.css / chat.css
 * 里散落硬编码的 px(8px / 16px / 20px 等)。第九轮补齐 `--space-1..7` 和
 * `--font-xs..2xl`,组件 CSS 渐进替换硬编码。
 *
 * 2026-07-21 调整:字号对齐 Tailwind 默认 16px 基线(2xs 12 / xs 13 / sm 14 /
 * base 16 / md 18 / lg 22 / xl 30 / 2xl 40),并用 `calc(Npx * var(--fs))` 让
 * `useFontScaleRoot` 注入的 `--fs` multiplier 在 0.875/1/1.25 三档线性缩放。
 * 测试从 calc() 中提取基础 Npx。
 *
 * 锁住契约:这些 token 必须存在 + 值在合理区间(间距 4-48,字号 12-40)。
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

/**
 * 提取 `--name: <expr>;` 中 <expr> 的首个 px 数值。
 * 支持两种语法:直接 `12px` 与 `calc(12px * var(--fs))`。
 */
function getTokenValue(css: string, name: string): number {
  const re = new RegExp(`--${name}:\\s*(?:calc\\()?([0-9.]+)px`);
  const m = css.match(re);
  if (!m) throw new Error(`未找到 --${name}: VALUEpx;`);
  return parseFloat(m[1]!);
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
      const v = getTokenValue(css, name);
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

describe('tokens.css 字号 token (--font-2xs..2xl)', () => {
  const css = readTokens();
  const FONT = {
    'font-2xs': 12,
    'font-xs': 13,
    'font-sm': 14,
    'font-base': 16,
    'font-md': 18,
    'font-lg': 22,
    'font-xl': 30,
    'font-2xl': 40,
  };
  for (const [name, expected] of Object.entries(FONT)) {
    it(`--${name} 必须存在且 = ${expected}px`, () => {
      const v = getTokenValue(css, name);
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