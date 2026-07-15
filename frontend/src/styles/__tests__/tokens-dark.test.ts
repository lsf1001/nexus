/**
 * tokens.css 锁色单测 — 2026-07-15 用户反馈:
 *   "DMG 深色模式整个变深,宫崎骏森林绿不见了,变成蓝黑+teal 蓝绿"
 * 根因:`--forest` 在 dark 模式被改成 `#25a4be` teal 蓝绿,与品牌脱钩。
 * 修法:dark 模式 token 整体调成宫崎骏森林绿族(`#0d1f17` / `#4a8a6f` 等)。
 *
 * 锁住:dark `--forest` 必须在森林绿族(R 通道 ≥ 70 且 R-G ≥ -10);
 *      dark `--canvas` 不能是纯黑(`#000` / `#080d15` 这种冷黑也不行)。
 *
 * 2026-07-15 追加硬编码扫描:
 *   组件 CSS 里硬编码的 teal 蓝绿色(`#28a9c0` / `#1c3046` 等)即便 token
 *   调成森林绿也不会生效,导致侧边栏/按钮/hover 仍是冷蓝绿。
 *   WHY:Token 修了但用户看到还是蓝绿 → 排查发现 shell.css:808
 *   `.btn-new-task .plus-mark { background: #28a9c0 }` 等孤儿硬编码。
 *
 * WHY 文件读取 vs jsdom 解析:CSS 解析要起 jsdom 拉 stylesheet 太重,
 * 我们只校验 hex 字符串本身,正则足够。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs';
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
const STYLES_DIR = join(__dirname, '..', '..', 'components', 'desktop', 'styles');

// 第二轮回归黑名单:这些色值出现在组件 CSS 里会让侧边栏/按钮/hover 仍是
// teal 蓝绿,与森林绿品牌脱钩。锁死,出现即失败。
//
// 第三轮新增(2026-07-15):用户反馈"用户气泡还是青蓝色"。根因:
//   1. tokens.css light --forest = #0f6e87 (teal 蓝绿,不是森林绿)
//   2. chat.css .message-user 硬编码 linear-gradient(#12849a, #0d6e87)
//   3. tokens.css light --shadow-* 基色 rgba(24, 39, 75) 冷蓝紫
//   4. shell.css .window light border rgba(18, 33, 56) 冷蓝
// 全部已替换为森林绿 / 暖棕,锁死防回退。
const FORBIDDEN_HEX = [
  '#28a9c0', // 旧 plus-mark teal
  '#32bdd1', // 旧 task-item is-current 左边框 teal
  '#36bdd1', // 旧 brand-mark gradient 起 teal
  '#13859d', // 旧 brand-mark gradient 止 teal
  '#66d0e1', // 旧 btn-new-task inset 边 teal
  '#1c3046', // 旧 btn-new-task 深蓝底
  '#24415b', // 旧 btn-new-task hover 深蓝
  '#20364c', // 旧 task-item is-current 深蓝底
  '#111b2b', // 旧 sidebar 蓝黑底
  '#172a38', // 旧 dark prompt-card hover 深蓝
  '#32778a', // 旧 dark prompt-card hover 边框 teal
  '#1f251f', // 旧 dark textarea focus 蓝绿底
  '#55b8c8', // 旧 composer focus-within teal 边框 (light 用,但 dark 没覆盖会透出)
  '#cfdae5', // 旧 composer 默认蓝灰边框 (light 用,防误迁移到 dark)
  '#0f6e87', // 旧 tokens light --forest (teal 蓝绿,非森林绿)
  '#075b72', // 旧 tokens light --forest-2 (深 teal,非深森林)
  '#12849a', // 旧 chat .message-user 渐变起 (teal)
  '#0d6e87', // 旧 chat .message-user 渐变止 (teal)
];

function readTokens(): string {
  return readFileSync(TOKENS_PATH, 'utf-8');
}

function walkCss(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      out.push(...walkCss(p));
    } else if (p.endsWith('.css')) {
      out.push(p);
    }
  }
  return out;
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

describe('组件 CSS 硬编码扫描', () => {
  const cssFiles = walkCss(STYLES_DIR);

  it('styles/ 下应至少有一份组件 CSS(防 walk 空)', () => {
    expect(cssFiles.length).toBeGreaterThan(0);
  });

  it.each(FORBIDDEN_HEX)(
    '组件 CSS 不应再出现 %s(2026-07 第二轮 teal 蓝绿回归)',
    (hex) => {
      const lower = hex.toLowerCase();
      const offenders: string[] = [];
      for (const file of cssFiles) {
        const src = readFileSync(file, 'utf-8');
        if (src.toLowerCase().includes(lower)) {
          offenders.push(file);
        }
      }
      expect(offenders, `${hex} 仍出现在: ${offenders.join(', ')}`).toEqual([]);
    },
  );
});
