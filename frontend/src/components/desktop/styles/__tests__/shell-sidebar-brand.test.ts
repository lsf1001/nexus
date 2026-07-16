/**
 * sidebar-brand-mark logo Claude Desktop 双色锁测试 — 2026-07-16 第十轮。
 *
 * WHY:第九轮先用森林绿 logo 修了"深色隐形"问题,但 sidebar 仍走森林绿
 * 不够 Claude Desktop。第十轮按 Claude Desktop 双色方案改造:
 *   - 浅色 sidebar ≈ 浅米白 → logo box = **白底 + 深字**
 *   - 深色 sidebar ≈ 近黑 → logo box = **黑底 + 白字**
 *   - 不再跟 forest 主题色耦合,sidebar 配色独立
 *
 * 锁定四条契约:
 *   1. `.sidebar-brand-mark` background 不能用 rgba(255,248,236,0.08)(隐形 bug 根因)
 *   2. `.sidebar-brand-mark` background **不能**用任何 0.0x 透明奶白
 *   3. 浅色 `.sidebar-brand-mark` background 是**白色**(白底深字)
 *   4. dark override `.sidebar-brand-mark` background 是**黑色**(黑底白字)
 *
 * 实现形式:读 shell.css 源文件,正则提取 `.sidebar-brand-mark` 块和
 * `.nexus-desktop[data-theme="dark"] .sidebar-brand-mark` 块,断言 background
 * 是白色/黑色字面量,或匹配 `var(--sidebar-bg)` token。
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

describe("sidebar-brand-mark logo (Claude Desktop 双色,浅白深黑)", () => {
  it(".sidebar-brand-mark 块必须存在", () => {
    const block = extractBlock(".sidebar-brand-mark");
    expect(block, "shell.css 缺 .sidebar-brand-mark { ... } 规则块").not.toBeNull();
  });

  it(".sidebar-brand-mark background **不能**用 rgba(255,248,236,0.08)(隐形 bug 根因)", () => {
    // WHY:0.08 透明奶白在森林绿 sidebar 背景下完全看不出 box,只剩 "N" 字符。
    const block = extractBlock(".sidebar-brand-mark");
    expect(block).not.toBeNull();
    expect(block!).not.toMatch(/background:\s*rgba\(\s*255\s*,\s*248\s*,\s*236\s*,\s*0\.08\s*\)/);
  });

  it(".sidebar-brand-mark background 必须**非**透明奶白(0.0x 系列)", () => {
    const block = extractBlock(".sidebar-brand-mark");
    expect(block).not.toBeNull();
    const lowAlphaCream = /background:\s*rgba\(\s*255\s*,\s*248\s*,\s*236\s*,\s*0\.0[0-9]\d*\s*\)/;
    expect(block!, "logo box 不能再用低 alpha 奶白作 background").not.toMatch(lowAlphaCream);
  });

  it("浅色 .sidebar-brand-mark background 必须是**白底**(Claude Desktop 浅色风格)", () => {
    // 第十轮新增契约:浅色 logo box 必须白色(或近白),配深字反色。
    // 允许:字面量 #ffffff / #fff / 白色 rgba;或 var(--sidebar-bg) 等 token。
    const block = extractBlock(".sidebar-brand-mark");
    expect(block).not.toBeNull();
    // 提取 background: 行(可能是 shorthand,只看 background: 后第一行)
    const bgMatch = block!.match(/background:\s*([^;]+);/);
    expect(bgMatch, "缺 background: 声明").not.toBeNull();
    const bgValue = (bgMatch?.[1] ?? "").trim();
    // 白底匹配:字面白色 / white / var(--sidebar-bg) / 浅米白系 #f7f5ef 等
    const isWhiteish =
      /^(?:#fff(?:fff)?|white|rgba?\(\s*255\s*,\s*255\s*,\s*255\b|var\(--sidebar-bg(?:-2)?\))/i.test(
        bgValue,
      );
    expect(isWhiteish, `浅色 logo box 必须是白色系,实际: ${bgValue}`).toBe(true);
  });

  it("dark 模式 .sidebar-brand-mark background 必须是**黑底**(Claude Desktop 深色风格)", () => {
    // 第十轮新增契约:深色 logo box 必须近黑。
    // WHY:双选择器并列(:root + .nexus-desktop)才能在 SettingsView 挂
    //     data-theme 到任一父元素时正确生效,单独 .nexus-desktop 选择器
    //     在文档根已经切 light 时会失效,实测 logo 仍显示黑底。
    const css_match = /:root\[data-theme="dark"\]\s+\.sidebar-brand-mark[\s\S]*?\}/.test(css) ||
      /\.nexus-desktop\[data-theme="dark"\]\s+\.sidebar-brand-mark[\s\S]*?\}/.test(css);
    expect(
      css_match,
      "shell.css 缺深色 .sidebar-brand-mark override(:root + .nexus-desktop 之一即可)",
    ).toBe(true);

    // 再用 extractBlock 抽出来,断言 background 是黑色
    let darkBlock = extractBlock(':root[data-theme="dark"] .sidebar-brand-mark');
    if (!darkBlock) darkBlock = extractBlock('.nexus-desktop[data-theme="dark"] .sidebar-brand-mark');
    expect(darkBlock, "深色 override 块抽不出").not.toBeNull();
    const bgMatch = darkBlock!.match(/background:\s*([^;]+);/);
    expect(bgMatch, "dark 块缺 background: 声明").not.toBeNull();
    const bgValue = (bgMatch?.[1] ?? "").trim();
    // 黑底匹配:字面黑 / black / var(--sidebar-bg) 等(深色模式 --sidebar-bg=#1f1f1f)
    const isBlackish =
      /^(?:#0{3,6}|black|rgba?\(\s*0\s*,\s*0\s*,\s*0\b|var\(--sidebar-bg(?:-2)?\))/i.test(
        bgValue,
      );
    expect(isBlackish, `深色 logo box 必须是黑色系,实际: ${bgValue}`).toBe(true);
  });

  it("dark 模式 .sidebar-brand-mark 必须有 explicit override 块(浅深二色各管各)", () => {
    // WHY:让深色模式独立配 logo box 颜色,token 自动适配不够 — Claude Desktop
    //     浅白深黑要硬区分,不能用同一个 var(--sidebar-bg) 跨主题靠 token 切换。
    const darkBlock =
      extractBlock(':root[data-theme="dark"] .sidebar-brand-mark') ||
      extractBlock('.nexus-desktop[data-theme="dark"] .sidebar-brand-mark');
    expect(
      darkBlock,
      "shell.css 缺 :root[data-theme=\"dark\"] .sidebar-brand-mark 或 .nexus-desktop 同名块",
    ).not.toBeNull();
    expect(darkBlock!).toMatch(/background:/);
  });
});