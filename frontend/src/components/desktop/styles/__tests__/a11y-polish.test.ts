/**
 * Task 6 a11y 锁测试 — 第十一轮 (2026-07-16) 产品级打磨。
 *
 * 锁 4 条契约:
 *   1. Sidebar btn-new-task 有 aria-label
 *   2. Sidebar recent-panel 有 aria-live="polite"
 *   3. PreferencesModal toggle 按钮(深色模式 / 思考过程)有 aria-pressed
 *   4. ChatArea ErrorBanner 外层有 role="status" + aria-live="assertive"
 */
import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SIDEBAR = readFileSync(
  resolve(HERE, "../../Sidebar.tsx"),
  "utf8"
);
const PREFERENCES = readFileSync(
  resolve(HERE, "../../PreferencesModal.tsx"),
  "utf8"
);
const CHATAREA = readFileSync(
  resolve(HERE, "../../../ChatArea/index.tsx"),
  "utf8"
);

describe("Task 6: a11y 契约锁", () => {
  it("Sidebar btn-new-task 必须有 aria-label 提示快捷键", () => {
    expect(SIDEBAR).toMatch(
      /className="btn-new-task"[\s\S]*?aria-label="新建对话 \(快捷键 Cmd\+N \/ Ctrl\+N\)"/
    );
  });

  it("Sidebar recent-panel 必须有 aria-live + aria-relevant 让屏幕阅读器播报", () => {
    expect(SIDEBAR).toMatch(
      /<div className="recent-panel"\s+aria-live="polite"\s+aria-relevant="additions text">/
    );
  });

  it("PreferencesModal 深色模式 toggle 必须有 aria-pressed", () => {
    expect(PREFERENCES).toMatch(/onClick=\{handleToggleDarkMode\}[\s\S]*?aria-pressed=\{darkMode\}/);
  });

  it("PreferencesModal 思考过程 toggle 必须有 aria-pressed", () => {
    expect(PREFERENCES).toMatch(/onClick=\{\(\) => setShowThinking\(!showThinking\)\}[\s\S]*?aria-pressed=\{showThinking\}/);
  });

  it("ChatArea ErrorBanner 外层必须有 role=status + aria-live=assertive", () => {
    expect(CHATAREA).toMatch(
      /\{lastError && \(\s*<div role="status" aria-live="assertive">\s*<ErrorBanner/
    );
  });
});