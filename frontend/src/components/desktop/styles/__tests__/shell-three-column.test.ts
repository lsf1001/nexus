/**
 * shell.css 三栏布局宽度链锁测试 — 2026-08-08 Round 7(Bug A 修复锁定)。
 *
 * WHY:viewport=900 + Artifacts 展开时,三栏 grid 把 .main 列压到 320px。
 * .chat-area-wrap 是 display:flex 但缺 min-width:0,flex 子项默认
 * min-width:auto,会按内容撑爆 grid cell(.chat-scroll 内容 411.9px
 * 撑出去,被 .main{overflow:hidden} 切右 ~92px — 用户截图"约/2/件"
 * 切边的真实触发场景)。
 *
 * 修复:.chat-area-wrap 加 min-width:0,强制约束在父 grid cell 内。
 *
 * 反向锁定(防回归):任何把 .chat-area-wrap 的 min-width:0 移除的
 * commit 都让这个测试红。
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

describe("shell.css 三栏布局宽度链(Round 7 Bug A 真实触发场景)", () => {
  it(".chat-area-wrap 声明了 min-width:0(防 flex 子项撑爆 grid cell)", () => {
    const block = extractBlock(".chat-area-wrap {");
    expect(block, "应存在 .chat-area-wrap 主规则块").not.toBeNull();
    const re = /(?:^|;|\n)\s*min-width\s*:\s*([^;]+);/;
    const m = block!.match(re);
    expect(m, "应声明 min-width").not.toBeNull();
    expect(m![1]!.trim()).toBe("0");
  });

  it(".main 同时声明了 min-width:0(防 grid 子项撑爆父)", () => {
    const block = extractBlock(".main {");
    expect(block, "应存在 .main 主规则块").not.toBeNull();
    const re = /(?:^|;|\n)\s*min-width\s*:\s*([^;]+);/;
    const m = block!.match(re);
    expect(m, ".main 也应声明 min-width").not.toBeNull();
    expect(m![1]!.trim()).toBe("0");
  });

  it(".main 保留 overflow:hidden(不能去掉,否则状态栏 float 会越界)", () => {
    // 这是 Bug A 真实触发器之一;修复不是去掉 overflow:hidden 而是
    // 让 .chat-area-wrap 适应它。回归锁定保持现状。
    const block = extractBlock(".main {");
    expect(block).toMatch(/overflow\s*:\s*hidden/);
  });
});