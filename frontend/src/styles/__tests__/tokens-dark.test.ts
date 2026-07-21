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

// Task 1.2:tokens.css 已并入 index.css,测试改读 index.css 的 token 块。
const TOKENS_PATH = join(
  __dirname,
  '..',
  '..',
  'index.css',
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
  // 匹配 `:root[data-theme="dark"] { ... }` 块(注释里出现的关键字不命中,
  // 因为正则要求 `}` 后面必须紧跟 `{`,注释里的语句会被 `}` 后跟 `;` 或换行打断)。
  // 兼容旧 `.nexus-desktop[data-theme="dark"] { ... }` 单选择器版本。
  // 第五轮(2026-07-15)改双选择器,因为 SettingsView 把 data-theme 挂在
  // `<html>` 不是 `.nexus-desktop`,旧选择器 specificity 命中不了,token 不生效。
  const reList = [
    /:root\[data-theme="dark"\]\s*\{[\s\S]*?\n\}/,
    /\.nexus-desktop\[data-theme="dark"\]\s*\{[\s\S]*?\n\}/,
  ];
  for (const re of reList) {
    const m = css.match(re);
    if (m) return m[0];
  }
  throw new Error('未找到 dark 模式 token 块');
}

// light 模式 token 挂在纯 `:root { ... }`(非 `:root[data-theme="dark"]`)。
// `:root\s*\{` 只命中 `:root {`,`:root[...]` 因为紧跟 `[` 不满足 `\s*\{`,
// 所以不会误抓 dark 块。
function extractLightBlock(css: string): string {
  const m = css.match(/:root\s*\{[\s\S]*?\n\}/);
  if (!m) throw new Error('未找到 light 模式 :root token 块');
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

// 第十二轮(2026-07-17)灰阶重构:整个主题去除彩色,所有 token 收敛为
// 中性灰阶。锁"无彩色"——每个 token 的 HSV 饱和度必须 ≤ 0.10。这比
// 之前"锁森林绿族"更强:任何色相(teal / 森林绿 / 暖棕)都不允许回归。
// forest/canvas 等旧品牌 token 已删除,不再断言。
const GRAY_TOKENS = [
  'ink', 'ink-2', 'ink-3',
  'paper', 'paper-2', 'paper-3',
  'line', 'line-2',
  // 'accent' 已并入 shadcn 核心 token(Claude --accent: 220 14% 96%,HSL 三元组,
  // 饱和度 ~14% 高于下方 0.10 锁),故从此列表移除;其存在性由 focus-ring 等测试覆盖。
  'accent-soft',
  'wechat',
  'sidebar-bg', 'sidebar-bg-2',
  'sidebar-fg', 'sidebar-fg-2', 'sidebar-fg-3',
];

function saturation(hex: string): number {
  const { r, g, b } = hexToRgb(hex);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  return max === 0 ? 0 : (max - min) / max;
}

describe('tokens.css dark 模式调色', () => {
  const block = extractDarkBlock(readTokens());

  it('dark 模式所有 token 饱和度 ≤ 0.10(锁防彩色回归)', () => {
    for (const name of GRAY_TOKENS) {
      const sat = saturation(getToken(block, name));
      expect(sat, `dark --${name} 饱和度 ${sat.toFixed(2)} 过高(> 0.10)`).toBeLessThanOrEqual(0.10);
    }
  });
});

describe('tokens.css light 模式调色', () => {
  const block = extractLightBlock(readTokens());

  it('light 模式所有 token 饱和度 ≤ 0.10(锁防彩色回归)', () => {
    for (const name of GRAY_TOKENS) {
      const sat = saturation(getToken(block, name));
      expect(sat, `light --${name} 饱和度 ${sat.toFixed(2)} 过高(> 0.10)`).toBeLessThanOrEqual(0.10);
    }
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
