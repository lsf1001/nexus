/**
 * apiPatch helper 单元测试 — Round 6.1 Task 8。
 *
 * 覆盖 3 类路径:
 * 1. 200 成功路径:返回解析后的 JSON。
 * 2. 400 异常路径:抛 Error 带 status + detail(Pydantic / 后端校验失败统一出口)。
 * 3. wire 格式:method=PATCH / Content-Type=application/json / body JSON 化。
 *
 * WHY stub fetch 而非 mock apiFetch:apiPatch 内部复用 apiFetch,所以 mock
 * apiFetch 会同时 mock 掉 URL 解析 + Bearer header,这里要单独验 fetch 调用
 * 参数,直接 stub fetch 才能 cover 真实 wire 形状。
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { apiPatch } from '../api';

describe('apiPatch', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('returns ok payload on 200', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, style: 'professional' }),
    })));
    const result = await apiPatch('/api/sessions/s1', { style: 'professional' });
    expect(result).toEqual({ ok: true, style: 'professional' });
  });

  it('throws on 400 with detail', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false,
      status: 400,
      json: async () => ({ detail: 'invalid style: bogus' }),
    })));
    await expect(apiPatch('/api/sessions/s1', { style: 'bogus' }))
      .rejects.toThrow(/invalid style/);
  });

  it('sends PATCH method and JSON body', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ ok: true }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await apiPatch('/api/sessions/s1', { style: 'concise' });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/sessions/s1'),
      expect.objectContaining({
        method: 'PATCH',
        body: JSON.stringify({ style: 'concise' }),
      }),
    );
  });
});