/**
 * sidebar-brand-mark logo 可见性锁测试 — 2026-07-16 第九轮 UI 重设计。
 *
 * WHY:Settings view 下,深色模式 sidebar 顶部 logo (`.sidebar-brand-mark`)
 * 在深森林绿 sidebar 背景下"隐形":background 用 `rgba(255,248,236,0.08)`
 * 仅 8% 透明奶白底,几乎与森林绿背景同色,用户只能看到孤零零的"N"字符,
 * 报"logo 怎么不见了"。
 *
 * 锁定两条契约:
 *   1. `.sidebar-brand-mark` 默认 background alpha >= 30%(至少比当前 0.08 高),
 *      用 forest 森林绿填底,而不是透明奶白。否则深色背景下不可见。
 *   2. 显式 dark 模式 override 块存在(`.nexus-desktop[data-theme="dark"]
 *      .sidebar-brand-mark`),再次确保 logo 在深色模式下有可见的 box 背景。
 *      对应其它 sidebar 子元素(.sidebar-brand-text strong/span、
 *      .sidebar-settings-btn、.sidebar-section-title)都有 dark override,
 *      brand-mark 不该是孤儿。
 *
 * 实现形式:读 shell.css 源文件,正则提取 `.sidebar-brand-mark { ... }` 块
 * 和 `.nexus-desktop[data-theme="dark"] .sidebar-brand-mark { ... }` 块,
 * 检查 background 是否仍为高度透明奶白(这是隐形 bug 的根因)。
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SHELL_CSS = resolve(HERE, "../shell.css");
const css = readFileSync(SHELL_CSS, "utf8");

/** 提取指定选择器后第一个 `{ ... }` 块(简单花括号平衡,够用)。 */
function extractBlock(selector: string): string | null {
  const idx = css.indexOf(selector);
  if (idx === -1) return null;
  const braceStart = css.indexOf("{", idx);
  if (braceStart === -1) return null;
  let depth = 1;
  for (let i = braceStart + 1; i < css.length; i++) {
    const ch = css[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return css.slice(braceStart + 1, i);
    }
  }
  return null;
}

describe("sidebar-brand-mark logo 可见性(深色模式不隐形)", () => {
  it(".sidebar-brand-mark 块必须存在", () => {
    const block = extractBlock(".sidebar-brand-mark");
    expect(block, "shell.css 缺 .sidebar-brand-mark { ... } 规则块").not.toBeNull();
  });

  it(".sidebar-brand-mark background **不能**用 rgba(255,248,236,0.08)(隐形 bug 根因)", () => {
    // WHY:0.08 透明奶白在森林绿 sidebar 背景下完全看不出 box,只剩 "N" 字符。
    // 修法:用 forest token 显式填底(实色或 >= 30% alpha),保证 logo 在两个主题都可见。
    const block = extractBlock(".sidebar-brand-mark");
    expect(block).not.toBeNull();
    expect(block!).not.toMatch(/background:\s*rgba\(\s*255\s*,\s*248\s*,\s*236\s*,\s*0\.08\s*\)/);
  });

  it(".sidebar-brand-mark background 必须**非**透明奶白(0.0x 系列),用森林绿实色填底", () => {
    const block = extractBlock(".sidebar-brand-mark");
    expect(block).not.toBeNull();
    // 反向:任何 0.x 系列透明奶白都拒绝(0.05 / 0.06 / 0.08 / 0.10 / 0.12 / 0.14 / 0.20)
    // 这些透明度在深森林绿背景下都不够"明显"做 logo box 背景。
    const lowAlphaCream = /background:\s*rgba\(\s*255\s*,\s*248\s*,\s*236\s*,\s*0\.0[0-9]\d*\s*\)/;
    expect(block!, "logo box 不能再用低 alpha 奶白作 background").not.toMatch(lowAlphaCream);
  });

  it(".sidebar-brand-mark 必须有 explicit dark mode override(跟其它 sidebar 子元素一致)", () => {
    // WHY:.sidebar-brand-text strong/span / .sidebar-settings-btn /
    //     .sidebar-section-title 都有 dark override,brand-mark 是孤儿。
    //     加 dark override 后,深色主题切换不会丢底色。
    const darkBlock = extractBlock(
      '.nexus-desktop[data-theme="dark"] .sidebar-brand-mark',
    );
    expect(
      darkBlock,
      "shell.css 缺 .nexus-desktop[data-theme=\"dark\"] .sidebar-brand-mark { ... } 块",
    ).not.toBeNull();
    expect(darkBlock!).toMatch(/background:/);
  });

  it(".sidebar-brand-mark dark override background **不能**用低 alpha 奶白", () => {
    const darkBlock = extractBlock(
      '.nexus-desktop[data-theme="dark"] .sidebar-brand-mark',
    );
    expect(darkBlock).not.toBeNull();
    const lowAlphaCream = /background:\s*rgba\(\s*255\s*,\s*248\s*,\s*236\s*,\s*0\.0[0-9]\d*\s*\)/;
    expect(
      darkBlock!,
      "dark 模式下 logo box 也必须用实色/高 alpha,不能再用低 alpha 奶白",
    ).not.toMatch(lowAlphaCream);
  });
});