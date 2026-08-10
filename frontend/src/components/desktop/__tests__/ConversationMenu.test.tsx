/**
 * ConversationMenu 测试 — Round 3 Task 3.5。
 *
 * 契约:
 *   - 触发后显示 4 项:复制 Session ID / 导出 Markdown / 创建分享链接 / 删除
 *   - 复制 Session ID → navigator.clipboard.writeText(sessionId)
 *   - 导出 Markdown → fetch /api/sessions/{id}/export.md → 触发 <a download> 触发器
 *   - 创建分享链接 → POST /api/sessions/{id}/share → 弹窗显示 URL + 复制按钮
 *
 * 用 jsdom URL.createObjectURL / Blob / document.execCommand 兜底模拟下载。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, waitFor } from '@testing-library/react';
import { ConversationMenu } from '../ConversationMenu';
import { apiFetch } from '../../../lib/api';

vi.mock('../../../lib/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    apiFetch: vi.fn(),
    resolveApiUrl: (input: string) => `http://127.0.0.1:30000${input.startsWith('/') ? '' : '/'}${input}`,
  };
});

const sessionId = 'sess-42';
const defaultProps = {
  open: true,
  sessionId,
  anchor: { x: 100, y: 200 },
  onClose: vi.fn(),
  onDelete: vi.fn(),
};

describe('ConversationMenu(Round 3 Task 3.5)', () => {
  beforeEach(() => {
    defaultProps.onClose.mockClear();
    defaultProps.onDelete.mockClear();
    vi.mocked(apiFetch).mockReset();
  });

  it('复制 Session ID → 调 navigator.clipboard.writeText(sessionId)', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    const { container } = render(<ConversationMenu {...defaultProps} />);
    const copyBtn = container.querySelector('[data-action="copy-id"]') as HTMLButtonElement;
    expect(copyBtn).not.toBeNull();
    await act(async () => {
      fireEvent.click(copyBtn);
    });
    expect(writeText).toHaveBeenCalledWith(sessionId);
  });

  it('导出 Markdown → fetch /export.md → 触发下载(<a download>)', async () => {
    const mdBody = '# Test Session\n\nHello world';
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(mdBody, {
        status: 200,
        headers: { 'Content-Type': 'text/markdown; charset=utf-8' },
      }),
    );

    // jsdom 没有 download 属性触发的完整流,monkey-patch HTMLAnchorElement.prototype.click
    // 以捕获 click 调用时的 anchor 状态 + download / href。
    const clickSpy = vi.fn();
    let captured: { href: string; download: string } | null = null;
    const origClick = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement & { download: string; href: string }) {
      captured = { href: this.href, download: this.download };
      clickSpy();
    };
    const origCreate = URL.createObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:fake');

    const { container } = render(<ConversationMenu {...defaultProps} />);
    const exportBtn = container.querySelector('[data-action="export"]') as HTMLButtonElement;
    expect(exportBtn).not.toBeNull();

    await act(async () => {
      fireEvent.click(exportBtn);
    });

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(`/api/sessions/${sessionId}/export.md`);
    });
    await waitFor(() => {
      expect(clickSpy).toHaveBeenCalled();
    });
    // 验证 anchor download 属性 + blob URL
    expect(captured).not.toBeNull();
    expect(captured!.download).toBe(`session-${sessionId}.md`);
    expect(captured!.href).toBe('blob:fake');

    // 还原
    HTMLAnchorElement.prototype.click = origClick;
    URL.createObjectURL = origCreate;
  });

  it('创建分享链接 → POST /share → 弹窗显示 URL + 复制按钮', async () => {
    const shareUrl = `/api/share/tk-xyz`;
    vi.mocked(apiFetch).mockResolvedValue(
      new Response(JSON.stringify({ token: 'tk-xyz', url: shareUrl, expires_at: '2026-08-12T00:00:00Z' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });

    const { container } = render(<ConversationMenu {...defaultProps} />);
    const shareBtn = container.querySelector('[data-action="share"]') as HTMLButtonElement;
    expect(shareBtn).not.toBeNull();

    await act(async () => {
      fireEvent.click(shareBtn);
    });

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith(
        `/api/sessions/${sessionId}/share`,
        expect.objectContaining({ method: 'POST' }),
      );
    });
    await waitFor(() => {
      // 显示分享 URL
      expect(container.textContent).toContain(shareUrl);
      // 复制按钮出现
      const copyShareBtn = container.querySelector('[data-action="copy-share-url"]') as HTMLButtonElement;
      expect(copyShareBtn).not.toBeNull();
    });
    // 点复制按钮 → 写完整 origin+url
    const copyShareBtn = container.querySelector('[data-action="copy-share-url"]') as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(copyShareBtn);
    });
    await waitFor(() => {
      expect(writeText).toHaveBeenCalled();
      const calledWith = writeText.mock.calls[0]?.[0] as string;
      expect(calledWith).toContain('/api/share/tk-xyz');
    });
  });
});