/**
 * SetupView 单元测试 — 2026-07-23 #3「测试连接」按钮真生效锁测。
 *
 * 契约:测试连接按钮 onClick 调 GET /api/models/default/test,按结果展示:
 *   - ok:true → "连接测试成功 ✓"
 *   - 401 → "鉴权失败"文案
 *   - 测试进行中 → 按钮 disabled + aria-busy
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { SetupView } from '../SetupView';
import { apiFetch } from '../../../lib/api';

vi.mock('../../../lib/api', () => ({ apiFetch: vi.fn() }));

function mockResponse(init: { ok: boolean; status?: number; text?: string }): Response {
  return {
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 400),
    text: async () => init.text ?? '',
    json: async () => ({ ok: init.ok }),
  } as unknown as Response;
}

describe('SetupView — 测试连接按钮(#3)', () => {
  beforeEach(() => {
    vi.mocked(apiFetch).mockReset();
  });

  it('点测试连接 → 调 GET /api/models/default/test 且成功文案出现', async () => {
    vi.mocked(apiFetch).mockResolvedValue(mockResponse({ ok: true }));
    render(<SetupView onDone={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith('/api/models/default/test', { method: 'GET' });
    });
    await waitFor(() => {
      expect(screen.getByText(/连接测试成功/)).toBeInTheDocument();
    });
  });

  it('测试返回 401 → status 显示鉴权失败文案', async () => {
    vi.mocked(apiFetch).mockResolvedValue(mockResponse({ ok: false, status: 401, text: 'unauthorized' }));
    render(<SetupView onDone={vi.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: '测试连接' }));

    await waitFor(() => {
      expect(screen.getByText(/鉴权失败/)).toBeInTheDocument();
    });
  });

  it('测试中按钮 disabled + aria-busy', async () => {
    let resolveFetch: (r: Response) => void = () => {};
    vi.mocked(apiFetch).mockReturnValue(
      new Promise<Response>((res) => {
        resolveFetch = res;
      }),
    );
    render(<SetupView onDone={vi.fn()} />);

    const btn = screen.getByRole('button', { name: '测试连接' });
    fireEvent.click(btn);

    // 测试进行中:按钮 disabled + aria-busy,文案变「测试中...」
    await waitFor(() => {
      const busyBtn = screen.getByRole('button', { name: '测试中...' });
      expect(busyBtn).toBeDisabled();
      expect(busyBtn).toHaveAttribute('aria-busy', 'true');
    });

    // 收尾 resolve 避免悬挂 promise
    await act(async () => {
      resolveFetch(mockResponse({ ok: true }));
    });
  });
});
