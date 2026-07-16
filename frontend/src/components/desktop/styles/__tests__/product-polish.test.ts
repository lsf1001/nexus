/**
 * 第十一轮 (2026-07-16) 产品级打磨 — 合并锁测试:
 *   Task 3 chat-scroll 渐隐边 + scroll affordance
 *   Task 4 loading-dot 三段 delay
 *   Task 5 prompt-card hover 视觉
 *   Task 6 a11y(aria-label/aria-live/aria-pressed)
 *   Task 7 footer-link--wechat 双色态
 *   Task 8 form input focus-visible + .hint.is-error 边条
 *
 * WHY:不再为每个 task 单独建文件 — 都是 CSS 文本锁,提取函数复用,
 * 一次 describe 跑完一组契约,失败时易定位到具体 task。
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const CHAT = readFileSync(resolve(HERE, "../chat.css"), "utf8");
const SHELL = readFileSync(resolve(HERE, "../shell.css"), "utf8");
const VIEWS = readFileSync(resolve(HERE, "../views.css"), "utf8");

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

describe("Task 3: chat-scroll 渐隐边 (background-attachment local)", () => {
  it(".chat-scroll 必须有 background-attachment: local 的 scroll affordance", () => {
    const body = extractBlock(CHAT, ".chat-scroll");
    expect(body, "chat.css 缺 .chat-scroll").not.toBeNull();
    expect(body!).toMatch(/background:\s*\n?\s*linear-gradient\(var\(--paper\)/);
    expect(body!).toMatch(/background-attachment:\s*local,\s*local,\s*scroll,\s*scroll/);
  });
});

describe("Task 4: loading-dot 三段 delay 节奏", () => {
  it(".loading-dot:nth-child(1/2/3) 必须各自有 animation-delay", () => {
    expect(CHAT).toMatch(/\.loading-dot:nth-child\(1\)\s*\{\s*animation-delay:\s*0ms/);
    expect(CHAT).toMatch(/\.loading-dot:nth-child\(2\)\s*\{\s*animation-delay:\s*150ms/);
    expect(CHAT).toMatch(/\.loading-dot:nth-child\(3\)\s*\{\s*animation-delay:\s*300ms/);
  });
});

describe("Task 5: prompt-card hover 视觉强化", () => {
  it(".prompt-card:hover 必须有 translateY + 阴影强化", () => {
    const body = extractBlock(SHELL, ".prompt-card:hover");
    expect(body, "shell.css 缺 .prompt-card:hover 规则").not.toBeNull();
    expect(body!).toMatch(/transform:\s*translateY\(-1px\)/);
    expect(body!).toMatch(/box-shadow:/);
  });
});

describe("Task 7: footer-link--wechat 双色态视觉", () => {
  it("未绑定态 footer-link 透明背景 + 间距 + padding", () => {
    const body = extractBlock(SHELL, ".sidebar-footer .footer-link");
    expect(body, "shell.css 缺 .sidebar-footer .footer-link").not.toBeNull();
    expect(body!).toMatch(/background:\s*transparent/);
    expect(body!).toMatch(/min-height:\s*38px/);
  });

  it("已连接态 footer-link--wechat 图标和 status 都变 wechat 绿", () => {
    const re = /\.sidebar-footer\s+\.footer-link--wechat\.is-connected\s+\.footer-link-icon[^{]*\{[^}]*color:\s*var\(--wechat\)/;
    expect(SHELL, "缺 is-connected 图标 wechat 绿").toMatch(re);
    const re2 = /\.sidebar-footer\s+\.footer-link--wechat\.is-connected\s+\.footer-link-status[^{]*\{[^}]*color:\s*var\(--wechat\)/;
    expect(SHELL, "缺 is-connected status wechat 绿").toMatch(re2);
  });
});

describe("Task 8: form input focus-visible 视觉统一", () => {
  it("setup / settings / wechat input focus-visible 必须有 forest 边框 + 光晕", () => {
    expect(VIEWS).toMatch(/setup-card input:focus-visible/);
    expect(VIEWS).toMatch(/settings-list input:focus-visible/);
    expect(VIEWS).toMatch(/setting-row input:focus-visible/);
    expect(VIEWS).toMatch(/wechat-bind-card input:focus-visible/);
    // box-shadow 光晕
    expect(VIEWS).toMatch(/box-shadow:\s*0\s+0\s+0\s+3px\s+rgba\(74,\s*124,\s*89/);
  });

  it(".hint.is-error 必须有左侧 3px 红边条", () => {
    const body = extractBlock(VIEWS, ".hint.is-error");
    expect(body, "views.css 缺 .hint.is-error").not.toBeNull();
    expect(body!).toMatch(/border-left:\s*3px\s+solid\s+#c05443/);
  });
});