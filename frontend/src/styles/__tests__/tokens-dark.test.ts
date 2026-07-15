/**
 * tokens.css 锁色单测 — 2026-07-15 用户反馈:
 *   "DMG 深色模式整个变深,宫崎骏森林绿不见了,变成蓝黑+teal 蓝绿"
 * 根因:`--forest` 在 dark 模式被改成 `#25a4be` teal 蓝绿,与品牌脱钩。
 * 修法:dark 模式 token 整体调成宫崎骏森林绿族(`#0d1f17` / `#4a8a6f` 等)。
 *
 * 锁住:dark `--forest` 必须在森林绿族(R 通道 ≥ 70 且 R-G ≥ -10);
 *      dark `--canvas` 不能是纯黑(`#000` / `#080d15` 这种冷黑也不行)。
 *
 * WHY 文件读取 vs jsdom 解析:CSS 解析要起 jsdom 拉 stylesheet 太重,
 * 我们只校验 hex 字符串本身,正则足够。
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const TOKENS_PATH = join(
  __dirname,
  '..',
  '..',
  'components',
  'desktop',
  'styles',
  'tokens.css',
);

function readTokens(): string {
  return readFileSync(TOKENS_PATH, 'utf-8');
}

function extractDarkBlock(css: string): string {
  const m = css.match(/\.nexus-desktop\[data-theme="dark"\][\s\S]*?\n\}/);
  if (!m) throw new Error('未找到 dark 模式 token 块');
  return m[0];
}

function getToken(block: string, name: string): string {
  const re = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{3,8})\\s*;`);
  const m = block.match(re);
  if (!m) throw new Error(`未找到 --${name}`);
  return m[1]!;
}

function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace('#', '');
  if (h.length === 3) {
    return {
      r: parseInt(h[0]! + h[0]!, 16),
      g: parseInt(h[1]! + h[1]!, 16),
      b: parseInt(h[2]! + h[2]!, 16),
    };
  }
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

describe('tokens.css dark 模式调色', () => {
  const block = extractDarkBlock(readTokens());

  it('--forest 在 dark 模式必须为森林绿族(非 teal 蓝绿)', () => {
    const forest = getToken(block, 'forest');
    const { r, g, b } = hexToRgb(forest);
    // 森林绿特征:G 通道是主色(最大);且不能是 teal/cyan 蓝绿
    expect(g, `forest=${forest} G 通道太低,可能偏灰`).toBeGreaterThanOrEqual(80);
    expect(g, `forest=${forest} G 应该是最大通道`).toBeGreaterThan(r);
    // teal 蓝绿典型值:#25a4be (b=190/r=37=5.1) 或 #43b8cf (b=207/r=67=3.1)
    // 森林绿族 b/r 应在 1.0~1.6 之间。> 2.0 视作 teal。
    const tealRatio = r === 0 ? Infinity : b / r;
    expect(tealRatio, `forest=${forest} B/R 比 ${tealRatio.toFixed(2)} 太大 → teal 蓝绿`).toBeLessThan(2.0);
  });

  it('--canvas 不能是纯黑或冷黑(避免与森林绿脱钩)', () => {
    const canvas = getToken(block, 'canvas');
    expect(canvas.toLowerCase()).not.toBe('#000000');
    expect(canvas.toLowerCase()).not.toBe('#080d15'); // 旧冷黑
    const { g, b } = hexToRgb(canvas);
    // 森林底:G 通道应该明显大于 B(避免 #0b111b 那种蓝黑)
    expect(g, `canvas=${canvas} G 太低,可能偏冷`).toBeGreaterThan(b - 20);
  });

  it('--ink 在 dark 模式应该是暖米白(非冷蓝白)', () => {
    const ink = getToken(block, 'ink');
    const { r, b } = hexToRgb(ink);
    // 暖白:R ≥ B 至少 5
    expect(r - b, `ink=${ink} R-B 差太小,可能偏冷`).toBeGreaterThanOrEqual(5);
  });
});
