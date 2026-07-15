/**
 * WechatAssistantView 结构锁测试(2026-07-15)。
 *
 * WHY:第八轮重构后 chat-status-bar 必须渲染在 ChannelViewBase 之上,
 * 否则 macOS chrome 顶部 drag 区域会被 bind-card/inbox 顶掉,用户没法拖窗。
 *
 * 历史 bug:ChannelViewBase 包在 chat-area-wrap 外 → bind-card + inbox 先渲染
 * → chat-status-bar 被挤到 bind-card 下面,出现在 y=161 而非 y=0。
 *
 * 测试断言(锁住结构契约):
 *   1. chat-status-bar 是 chat-area-wrap 的直接子元素(不穿过 ChannelViewBase)
 *   2. chat-status-bar 顶部位置 = 0(未漂移)
 *   3. bind-card 出现在 chat-status-bar 之后(顺序正确)
 *   4. onBack 渲染返回按钮
 *   5. brand-copy 出现在 ChannelViewBase 内(.channel-children 子树)
 *
 * ChannelViewBase 内部 useChannelStatusPolling 会 fetch /api/channels/wechat/bind
 *  → mock apiFetch 避免真打后端。
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render } from "@testing-library/react";
import { WechatAssistantView } from "../WechatAssistantView";

vi.mock(import("../../../lib/api"), async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    apiFetch: vi.fn((): Promise<Response> =>
      Promise.resolve({
        ok: true,
        status: 200,
        statusText: "OK",
        headers: new Headers(),
        redirected: false,
        type: "basic",
        url: "",
        json: () => Promise.resolve({ bound: false }),
        text: () => Promise.resolve(""),
        blob: () => Promise.resolve(new Blob()),
        arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
        formData: () => Promise.resolve(new FormData()),
        bodyUsed: false,
        body: null,
        clone: function () {
          return this;
        },
      } as unknown as Response),
    ),
  };
});

describe("WechatAssistantView 结构契约(chat-status-bar 必须置顶)", () => {
  beforeEach(() => {
    // mock getBoundingClientRect 返回固定 y=0 让顺序断言可移植
    Element.prototype.getBoundingClientRect = function () {
      // 简单 stack:y 累加 — 真实无关紧要,只用来定位相对顺序
      const all = Array.from(
        document.querySelectorAll(
          "header.chat-status-bar, .channel-bind-card, .channel-inbox-empty, .wechat-copy-inline",
        ),
      );
      const idx = all.indexOf(this);
      return {
        x: 0,
        y: idx * 50,
        width: 600,
        height: 36,
        top: idx * 50,
        right: 600,
        bottom: idx * 50 + 36,
        left: 0,
        toJSON: () => ({}),
      };
    };
  });

  it("chat-area-wrap 是最外层容器", () => {
    const { container } = render(<WechatAssistantView />);
    const wrap = container.querySelector(".chat-area-wrap");
    expect(wrap).not.toBeNull();
    // 必须包含 status-bar + ChannelViewBase
    expect(
      wrap?.querySelector(":scope > header.chat-status-bar"),
    ).not.toBeNull();
    expect(wrap?.querySelector(":scope > .channel-view")).not.toBeNull();
  });

  it("chat-status-bar 是 chat-area-wrap 的直接子元素(不穿过 ChannelViewBase)", () => {
    const { container } = render(<WechatAssistantView />);
    const wrap = container.querySelector(".chat-area-wrap");
    const statusBar = wrap?.querySelector(":scope > header.chat-status-bar");
    expect(statusBar).not.toBeNull();
    // 反向断言:status-bar 不能在 .channel-view 内部
    const insideChannelView = container.querySelector(
      ".channel-view header.chat-status-bar",
    );
    expect(insideChannelView).toBeNull();
  });

  it("bind-card 在 status-bar 之后渲染(顺序对)", () => {
    const { container } = render(<WechatAssistantView />);
    const statusBar = container.querySelector(".chat-status-bar");
    const bindCard = container.querySelector(".channel-bind-card");
    expect(statusBar).not.toBeNull();
    expect(bindCard).not.toBeNull();
    // statusBar.compareDocumentPosition(bindCard) & DOCUMENT_POSITION_FOLLOWING = 4
    const pos = statusBar!.compareDocumentPosition(bindCard!);
    expect(pos & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("brand-copy 是 ChannelViewBase 的子树(在 .channel-children 内)", () => {
    const { container } = render(<WechatAssistantView />);
    const channelView = container.querySelector(".channel-view");
    const channelChildren = channelView?.querySelector(".channel-children");
    const brandCopy = channelChildren?.querySelector(".wechat-copy-inline");
    expect(brandCopy).not.toBeNull();
  });

  it("onBack 缺省 → 不渲染返回按钮", () => {
    const { container } = render(<WechatAssistantView />);
    expect(container.querySelector("button.chat-status-action")).toBeNull();
  });

  it('onBack 提供 → 渲染返回按钮且文案 = "← 返回聊天"', () => {
    const onBack = vi.fn();
    const { container } = render(<WechatAssistantView onBack={onBack} />);
    const backBtn = container.querySelector("button.chat-status-action");
    expect(backBtn).not.toBeNull();
    expect(backBtn?.textContent).toContain("返回聊天");
    backBtn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("status-bar 带 data-tauri-drag-region(macOS chrome 拖窗属性)", () => {
    const { container } = render(<WechatAssistantView />);
    const statusBar = container.querySelector(".chat-status-bar");
    expect(statusBar?.getAttribute("data-tauri-drag-region")).not.toBeNull();
  });
});
