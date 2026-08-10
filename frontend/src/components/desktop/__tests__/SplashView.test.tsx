/**
 * SplashView 单元测试 — 2026-07-23 #21 retry 真重启后端锁测。
 *
 * 契约:Failed 态点「重试」→ 调 invoke('restart_sidecar')(不再 reload webview):
 *   - invoke 成功 → status 回到 Starting(显示 loading)
 *   - invoke 失败 → status 变 Failed 且 data 含「重启失败」
 *
 * mock 策略:
 *   - @tauri-apps/api/event.listen:捕获 runtime-status 回调,测试里手动派发
 *     Failed 把组件驱到错误态。
 *   - @tauri-apps/api/core.invoke:按用例 resolve / reject。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import type { RuntimeStatus } from '../SplashView';

// 捕获 listen 注册的回调,供测试手动派发事件。
let listenCallback: ((e: { payload: RuntimeStatus }) => void) | null = null;

vi.mock('@tauri-apps/api/event', () => ({
  listen: vi.fn((_name: string, cb: (e: { payload: RuntimeStatus }) => void) => {
    listenCallback = cb;
    return Promise.resolve(() => {});
  }),
}));

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }));

import { SplashView } from '../SplashView';
import { invoke } from '@tauri-apps/api/core';

async function driveToFailed(msg: string): Promise<void> {
  await waitFor(() => expect(listenCallback).not.toBeNull());
  await act(async () => {
    listenCallback!({ payload: { type: 'Failed', data: msg } });
  });
}

describe('SplashView — retry 重启后端(#21)', () => {
  beforeEach(() => {
    listenCallback = null;
    vi.mocked(invoke).mockReset();
  });

  it('Failed 态点重试 → 调 invoke("restart_sidecar")', async () => {
    vi.mocked(invoke).mockResolvedValue(undefined);
    render(<SplashView />);
    await driveToFailed('后端崩了');

    fireEvent.click(screen.getByRole('button', { name: '重试' }));

    await waitFor(() => {
      expect(invoke).toHaveBeenCalledWith('restart_sidecar');
    });
  });

  it('invoke 成功 → status 回到 Starting(显示启动中)', async () => {
    vi.mocked(invoke).mockResolvedValue(undefined);
    render(<SplashView />);
    await driveToFailed('后端崩了');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '重试' }));
    });

    await waitFor(() => {
      expect(screen.getByText(/正在启动 Nexus/)).toBeInTheDocument();
    });
    // 错误态元素消失
    expect(screen.queryByText('后端启动失败')).toBeNull();
  });

  it('invoke 失败 → status 变 Failed 且含「重启失败」', async () => {
    vi.mocked(invoke).mockRejectedValue(new Error('boom'));
    render(<SplashView />);
    await driveToFailed('后端崩了');

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: '重试' }));
    });

    await waitFor(() => {
      expect(screen.getByText(/重启失败/)).toBeInTheDocument();
    });
  });
});
