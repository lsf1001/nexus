/**
 * chat.css 对话工作区宽度链锁测试 — 2026-08-07 Round 7(Bug A 修复锁定)。
 *
 * WHY:1280 整窗 + sidebar 260 下,chat-scroll 被 `width: min(720px, 100%)`
 * + box-sizing:border-box + padding 34px 压到内容宽 652px;而 .message-list
 * (max-width 790) / .message-bubble (max-width 700) 永远够不着声明宽度,
 * 叠加 .main { overflow: hidden } 硬裁无滚动条 → 长 Markdown 段落右侧
 * 字符被切(用户截图"约"/"2"/"件"切边)。
 *
 * 修复:chat-scroll 不再走 720 限宽组,改为撑满父;真正的居中限宽交给
 * .message-list(720)。本测试锁三件事:
 *   1. .chat-scroll 不在共享 720 限宽的选择器组里
 *   2. .message-list max-width 仍是 720(后置覆盖块回归)
 *   3. .message-bubble max-width 仍是 680(回归)
 *
 * 反向锁定(防止回归):如果有人手贱把 .chat-scroll 加回 720 限宽组,
 * 本测试即红;同样 .message-list 后置覆盖回归到 790 也会红。
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const CHAT_CSS = resolve(HERE, "../chat.css");
const css = readFileSync(CHAT_CSS, "utf8");

/** 提取指定选择器后第一个 `{ ... }` 块(简单花括号平衡,够用)。 */
function extractBlock(selector: string): string | null {
  const idx = css.indexOf(selector);
  if (idx < 0) return null;
  const start = css.indexOf("{", idx);
  if (start < 0) return null;
  let depth = 1;
  for (let i = start + 1; i < css.length; i++) {
    const ch = css[i];
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return css.slice(start + 1, i);
    }
  }
  return null;
}

/** 在两个 anchor 之间的内容里提取第一个声明。 */
function findProp(block: string, prop: string): string | null {
  const re = new RegExp(`(?:^|;|\\n)\\s*${prop}\\s*:\\s*([^;]+);`);
  const m = block.match(re);
  return m ? m[1]!.trim() : null;
}

describe("chat.css 对话工作区宽度链(Round 7 Bug A)", () => {
  it("chat-scroll 不在 720 限宽共享组里(否则 .main{overflow:hidden} 切右边)", () => {
    // 共享 720 限宽组的注释现在只标 composer-shell / empty-state。
    // 反向锁定:任何把 .chat-scroll 加回这个组的 commit 都会让这个 case 红。
    const groupBlock = extractBlock(
      ".composer-shell,\n.empty-state {",
    ) ?? extractBlock(".composer-shell, .empty-state {");
    expect(groupBlock, "应存在 composer-shell + empty-state 的 720 限宽组").not.toBeNull();
    expect(groupBlock).not.toMatch(/\.chat-scroll/);
    expect(findProp(groupBlock!, "width")).toBe("min(720px, 100%)");
  });

  it(".message-list 后置覆盖 max-width 回到 720(回归锁定)", () => {
    // 后置覆盖块在 css 后段(对话工作区视觉升级那段)。
    // 直接搜所有 .message-list { ... } 块取最后一个 max-width。
    const re = /\.message-list\s*\{[^}]*max-width\s*:\s*(\d+)px/g;
    const matches = [...css.matchAll(re)];
    expect(matches.length).toBeGreaterThan(0);
    const last = matches[matches.length - 1]!;
    expect(last[1]).toBe("720");
  });

  it(".message-bubble 后置覆盖 max-width 是 680(回归锁定)", () => {
    const re = /\.message-bubble\s*\{[^}]*max-width\s*:\s*(\d+)px/g;
    const matches = [...css.matchAll(re)];
    expect(matches.length).toBeGreaterThan(0);
    const last = matches[matches.length - 1]!;
    expect(last[1]).toBe("680");
  });

  it(".chat-scroll 主规则没被限定 720(正向:撑满父)", () => {
    // 主规则 padding 在 L14(28px)和后置覆盖 L1089(34px);width 字段不应
    // 包含 720。允许 width 未声明(默认 auto = 撑满父);只要不出现 720 即可。
    const block = extractBlock(".chat-scroll {");
    expect(block).not.toBeNull();
    const w = findProp(block!, "width");
    if (w !== null) {
      expect(w).not.toMatch(/720/);
    }
  });
});