/**
 * useGlobalShortcuts 锁测试 — 第十一轮 (2026-07-16) 产品级打磨。
 *
 * 锁 4 条契约:
 *   1. Cmd+N(modKey + n)触发 onNewTask
 *   2. Cmd+K(modKey + k)触发 onFocusSearch
 *   3. Cmd+/(modKey + /)触发 onFocusComposer
 *   4. Esc 触发 onCloseModal(无 modKey)
 *
 * 通过 React Testing Library 的 renderHook 触发 keydown 事件,
 * 用 vi.fn() 验证 callback 被调用次数。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useGlobalShortcuts } from "../useGlobalShortcuts";
import { useStore } from "../../../../store";

function fireKey(opts: {
  key: string;
  metaKey?: boolean;
  ctrlKey?: boolean;
  shiftKey?: boolean;
  altKey?: boolean;
  target?: EventTarget | null;
}): void {
  const event = new KeyboardEvent("keydown", {
    key: opts.key,
    metaKey: opts.metaKey ?? false,
    ctrlKey: opts.ctrlKey ?? false,
    shiftKey: opts.shiftKey ?? false,
    altKey: opts.altKey ?? false,
    bubbles: true,
    cancelable: true,
  });
  if (opts.target !== undefined) {
    Object.defineProperty(event, "target", { value: opts.target });
  }
  window.dispatchEvent(event);
}

describe("useGlobalShortcuts (Cmd+N/K// + Esc)", () => {
  beforeEach(() => {
    // 每个 case 干净的 window listener
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("Cmd+N 触发 onNewTask", () => {
    const onNewTask = vi.fn();
    renderHook(() => useGlobalShortcuts({ onNewTask }));
    fireKey({ key: "n", metaKey: true });
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });

  it("Ctrl+N 同样触发 onNewTask(跨平台)", () => {
    const onNewTask = vi.fn();
    renderHook(() => useGlobalShortcuts({ onNewTask }));
    fireKey({ key: "n", ctrlKey: true });
    expect(onNewTask).toHaveBeenCalledTimes(1);
  });

  it("Cmd+K 触发 onFocusSearch", () => {
    const onFocusSearch = vi.fn();
    renderHook(() => useGlobalShortcuts({ onFocusSearch }));
    fireKey({ key: "k", metaKey: true });
    expect(onFocusSearch).toHaveBeenCalledTimes(1);
  });

  it("Cmd+/ 触发 onFocusComposer", () => {
    const onFocusComposer = vi.fn();
    renderHook(() => useGlobalShortcuts({ onFocusComposer }));
    fireKey({ key: "/", metaKey: true });
    expect(onFocusComposer).toHaveBeenCalledTimes(1);
  });

  it("Esc 触发 onCloseModal(无 modKey)", () => {
    const onCloseModal = vi.fn();
    renderHook(() => useGlobalShortcuts({ onCloseModal }));
    fireKey({ key: "Escape" });
    expect(onCloseModal).toHaveBeenCalledTimes(1);
  });

  it("没有对应 callback 时不会 throw", () => {
    renderHook(() => useGlobalShortcuts({}));
    fireKey({ key: "n", metaKey: true });
    fireKey({ key: "Escape" });
    // 不报错即通过
  });

  it("修饰键组合带 Shift 不触发(避免 Cmd+Shift+N 类冲突)", () => {
    const onNewTask = vi.fn();
    renderHook(() => useGlobalShortcuts({ onNewTask }));
    fireKey({ key: "n", metaKey: true, shiftKey: true });
    expect(onNewTask).not.toHaveBeenCalled();
  });

  // 第十一轮(三栏重构,2026-07-20):Cmd+\ 翻转 Artifacts 折叠态
  it("Cmd+\\ 翻转 Artifacts 折叠态", () => {
    useStore.getState().setArtifactsCollapsed(true);
    renderHook(() => useGlobalShortcuts({}));
    fireKey({ key: "\\", metaKey: true });
    expect(useStore.getState().artifactsCollapsed).toBe(false);
    fireKey({ key: "\\", metaKey: true });
    expect(useStore.getState().artifactsCollapsed).toBe(true);
  });

  it("Ctrl+\\ 也触发(Win/Linux 通用)", () => {
    useStore.getState().setArtifactsCollapsed(true);
    renderHook(() => useGlobalShortcuts({}));
    fireKey({ key: "\\", ctrlKey: true });
    expect(useStore.getState().artifactsCollapsed).toBe(false);
  });

  it("Shift+\\ 不触发折叠(只 plain Cmd+\\)", () => {
    useStore.getState().setArtifactsCollapsed(true);
    renderHook(() => useGlobalShortcuts({}));
    fireKey({ key: "|", metaKey: true, shiftKey: true }); // Shift+\ 产出 |
    expect(useStore.getState().artifactsCollapsed).toBe(true);
  });

  // 第十一轮-3(2026-07-23,#9 键盘守卫):modKey 快捷键在文本输入元素内放行,
  // 不再 preventDefault + 不触发 callback。让浏览器原生行为跑(Cmd+N 不再
  // 在 textarea 内被拦 → 切会话副作用消失)。
  describe("text input focus guard (第十一轮-3)", () => {
    function makeTextarea(): HTMLTextAreaElement {
      const ta = document.createElement("textarea");
      Object.defineProperty(ta, "tagName", { value: "TEXTAREA", configurable: true });
      return ta;
    }
    function makeInput(): HTMLInputElement {
      const input = document.createElement("input");
      Object.defineProperty(input, "tagName", { value: "INPUT", configurable: true });
      return input;
    }
    function makeContentEditable(): HTMLDivElement {
      const div = document.createElement("div");
      Object.defineProperty(div, "isContentEditable", { value: true, configurable: true });
      return div;
    }

    it("Cmd+N 在 textarea 内不触发 onNewTask", () => {
      const onNewTask = vi.fn();
      renderHook(() => useGlobalShortcuts({ onNewTask }));
      fireKey({ key: "n", metaKey: true, target: makeTextarea() });
      expect(onNewTask).not.toHaveBeenCalled();
    });

    it("Cmd+K 在 input 内不触发 onFocusSearch", () => {
      const onFocusSearch = vi.fn();
      renderHook(() => useGlobalShortcuts({ onFocusSearch }));
      fireKey({ key: "k", metaKey: true, target: makeInput() });
      expect(onFocusSearch).not.toHaveBeenCalled();
    });

    it("Cmd+/ 在 contenteditable 内不触发 onFocusComposer", () => {
      const onFocusComposer = vi.fn();
      renderHook(() => useGlobalShortcuts({ onFocusComposer }));
      fireKey({ key: "/", metaKey: true, target: makeContentEditable() });
      expect(onFocusComposer).not.toHaveBeenCalled();
    });

    it("Cmd+\\ 在 textarea 内不翻转 Artifacts 折叠态", () => {
      useStore.getState().setArtifactsCollapsed(true);
      renderHook(() => useGlobalShortcuts({}));
      fireKey({ key: "\\", metaKey: true, target: makeTextarea() });
      expect(useStore.getState().artifactsCollapsed).toBe(true);
    });

    it("Cmd+= 在 textarea 内不触发 onZoomIn", () => {
      const onZoomIn = vi.fn();
      renderHook(() => useGlobalShortcuts({ onZoomIn }));
      fireKey({ key: "=", metaKey: true, target: makeTextarea() });
      expect(onZoomIn).not.toHaveBeenCalled();
    });

    it("focus 在 div(非输入元素)时 Cmd+N 仍正常触发 onNewTask", () => {
      const onNewTask = vi.fn();
      const div = document.createElement("div");
      renderHook(() => useGlobalShortcuts({ onNewTask }));
      fireKey({ key: "n", metaKey: true, target: div });
      expect(onNewTask).toHaveBeenCalledTimes(1);
    });
  });
});
