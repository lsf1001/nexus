/**
 * 全局焦点环硬边描边锁测试 — 第十一轮 (2026-07-16) 产品级打磨。
 *
 * WHY:用户决定焦点环走"硬边描边"(2px outline + offset 2px,极简风)。
 *   - 浅色模式 = 纯黑 outline(在浅米白 sidebar / 白纸面都清晰可见)
 *   - 深色模式 = 纯白 outline(在近黑 sidebar / 苔藓纸面都清晰可见)
 *
 * 实现形式:读 tokens.css / shell.css 源文件,字符串定位 + 简单花括号平衡提取:
 *   - 找 `:root {` 起点 → 平衡到 `}` → 抽 `--focus-ring` 值(浅色必须是 #000000)
 *   - 找 `:root[data-theme="dark"] {` 起点 → 平衡到 `}` → 抽 `--focus-ring` 值
 *   - 找 `.nexus-desktop *:focus-visible {` 起点 → 平衡到 `}` → 抽规则体
 *   - aria-hidden / sketch-line 排除规则
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const TOKENS_CSS = resolve(HERE, "../tokens.css");
const SHELL_CSS = resolve(HERE, "../shell.css");
const tokens = readFileSync(TOKENS_CSS, "utf8");
const shell = readFileSync(SHELL_CSS, "utf8");

function extractBlock(source: string, selector: string): string | null {
  const idx = source.indexOf(selector);
  if (idx === -1) return null;
  const braceStart = source.indexOf("{", idx);
  if (braceStart === -1) return null;
  let depth = 1;
  for (let i = braceStart + 1; i < source.length; i++) {
    const ch = source[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return source.slice(braceStart + 1, i);
    }
  }
  return null;
}

function extractVar(body: string, varName: string): string | null {
  const lines = body.split("\n");
  let inComment = false;
  for (const line of lines) {
    let l = line;
    if (inComment) {
      const end = l.indexOf("*/");
      if (end === -1) continue;
      l = l.slice(end + 2);
      inComment = false;
    }
    const start = l.indexOf("/*");
    if (start !== -1) {
      const end = l.indexOf("*/", start + 2);
      if (end === -1) {
        inComment = true;
        l = l.slice(0, start);
      } else {
        l = l.slice(0, start) + l.slice(end + 2);
      }
    }
    const m = l.match(new RegExp(`${varName}\\s*:\\s*([^;]+);`));
    if (m) return m[1].trim();
  }
  return null;
}

describe("全局焦点环 (硬边描边 浅黑深白)", () => {
  it("light :root 必须定义 --focus-ring = #000000 (纯黑硬边)", () => {
    const body = extractBlock(tokens, ":root");
    expect(body, "tokens.css 缺 :root { ... } 规则块").not.toBeNull();
    const v = extractVar(body!, "--focus-ring");
    expect(v, ":root 块缺 --focus-ring 定义").not.toBeNull();
    expect(v).toBe("#000000");
  });

  it("dark :root 必须定义 --focus-ring = #ffffff (纯白硬边)", () => {
    // WHY:简单 indexOf(:root[data-theme="dark"]) 会被 tokens.css 顶部注释里的
    // 提及字串误命中,所以用 multiline 正则限定"选择器位置" = 行首 + 选择器后跟 {。
    // tokens.css:102 的选择器前面是换行,选择器后紧跟 { 开头。
    const re = /^\s*:root\[data-theme="dark"\]\s*\{/m;
    const match = re.exec(tokens);
    expect(match, "tokens.css 缺 :root[data-theme=dark] { 块").not.toBeNull();
    const braceStart = match!.index + match![0].length - 1;
    let depth = 1;
    let endIdx = -1;
    for (let i = braceStart + 1; i < tokens.length; i++) {
      const ch = tokens[i];
      if (ch === "{") depth++;
      else if (ch === "}") {
        depth--;
        if (depth === 0) {
          endIdx = i;
          break;
        }
      }
    }
    expect(endIdx, "dark 块没匹配到闭合 }").toBeGreaterThan(braceStart);
    const body = tokens.slice(braceStart + 1, endIdx);
    const v = extractVar(body, "--focus-ring");
    expect(v, "dark 块缺 --focus-ring 定义").not.toBeNull();
    expect(v).toBe("#ffffff");
  });

  it("shell.css 必须有 .nexus-desktop *:focus-visible 规则(2px outline + offset 2px)", () => {
    const body = extractBlock(shell, ".nexus-desktop *:focus-visible");
    expect(body, "shell.css 缺 .nexus-desktop *:focus-visible { ... } 规则").not.toBeNull();
    expect(body!).toMatch(/outline:\s*2px\s+solid\s+var\(--focus-ring\)/);
    expect(body!).toMatch(/outline-offset:\s*2px/);
  });

  it("装饰元素 (aria-hidden=true / .sketch-line) 必须排除焦点环", () => {
    const re = /\.nexus-desktop\s+\[aria-hidden="true"\]:focus-visible[^{]*\{[^}]*outline:\s*none/;
    expect(shell, "缺 [aria-hidden=true]:focus-visible 排除规则").toMatch(re);
    const re2 = /\.nexus-desktop\s+\.sketch-line:focus-visible[^{]*\{[^}]*outline:\s*none/;
    expect(shell, "缺 .sketch-line:focus-visible 排除规则").toMatch(re2);
  });
});
