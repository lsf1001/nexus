/**
 * useVoiceRecorder 单测 — Round 4 T4.2 (2026-08-05 加)。
 *
 * 覆盖三类路径:
 *   1. 正常:start → mock MediaRecorder 收到 dataavailable → stop → fetch /api/asr → onTranscribed
 *   2. 异常 a:getUserMedia 拒绝(NotAllowedError)→ state=error + 友好文案
 *   3. 异常 b:浏览器不支持 MediaRecorder → state=error + 提示文案
 *
 * 边界:
 *   - 录音 chunks 全空 → 不发 fetch,直接回 idle(避免空文件提交报错)
 *
 * WHY:hook 是 MicButton 的状态机核心,逻辑集中在 hook 单测,
 * 组件层只测渲染 / 交互(避免双重覆盖)。Mock MediaRecorder 走最小
 * 鸭子类型 — 只暴露 hook 用到的字段(start / stop / ondataavailable /
 * onstop / mimeType),让 vi.fn() 直接接管。
 */
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { act, renderHook } from '@testing-library/react';
import { useVoiceRecorder } from '../useVoiceRecorder';

type MediaRecorderMock = {
  start: () => void;
  stop: () => void;
  ondataavailable: ((e: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  onerror: ((e: Event) => void) | null;
  mimeType: string;
};

interface FakeTrack {
  stop: () => void;
}

interface FakeStream {
  getTracks: () => FakeTrack[];
}

function makeFakeStream(): FakeStream {
  const tracks = [{ stop: vi.fn() }, { stop: vi.fn() }];
  return { getTracks: () => tracks };
}

/**
 * 用 class 副作用装 mock。jsdom `class` constructor 不能 return 非 this 对象,
 * 所以 hook `new MediaRecorder(stream)` 拿到的实例的 start/stop / ondataavailable /
 * onstop 必须是同一个全局对象 — 我们把 recorder 通过全局变量暴露,hook 拿到后再
 * 调用我们的 mock。
 */
function installMediaRecorderMock(recorder: MediaRecorderMock): void {
  // vi.fn() 实现 — hook 调到的就是这俩
  recorder.start = vi.fn();
  recorder.stop = vi.fn(() => {
    if (recorder.ondataavailable) {
      recorder.ondataavailable({ data: new Blob(['x'], { type: 'audio/webm' }) });
    }
    if (recorder.onstop) recorder.onstop();
  });
  recorder.mimeType = 'audio/webm';

  // @ts-expect-error jsdom 未实现 MediaRecorder
  globalThis.MediaRecorder = class {
    constructor(_stream: MediaStream) {
      // 副作用:把 hook 后挂的回调绑到 mock 实例上,stop 调用时 trigger。
      // defineProperty + get/set 让 hook `recorder.ondataavailable = ...` 落到 mock
      // 而不是 instance 自己的属性(shadow getter)。
      Object.defineProperty(this, 'ondataavailable', {
        get() { return recorder.ondataavailable; },
        set(v) { recorder.ondataavailable = v; },
        configurable: true,
      });
      Object.defineProperty(this, 'onstop', {
        get() { return recorder.onstop; },
        set(v) { recorder.onstop = v; },
        configurable: true,
      });
      Object.defineProperty(this, 'onerror', {
        get() { return recorder.onerror; },
        set(v) { recorder.onerror = v; },
        configurable: true,
      });
      Object.defineProperty(this, 'mimeType', {
        get() { return recorder.mimeType; },
        configurable: true,
      });
      // start/stop 在 mock class 用了闭包指向 recorder 对象;不抢字段名
      // —— TS 不知道"这是注册"模式,简单用对象字面量 + 类型断言
      (this as unknown as { start: () => void }).start = () => recorder.start();
      (this as unknown as { stop: () => void }).stop = () => recorder.stop();
    }
    static isTypeSupported(t: string) {
      return t === 'audio/webm' || t === 'audio/webm;codecs=opus';
    }
  };
}

function installGetUserMediaMock(stream: FakeStream, reject?: Error): void {
  // @ts-expect-error jsdom 未实现 navigator.mediaDevices
  globalThis.navigator.mediaDevices = {
    getUserMedia: reject
      ? vi.fn().mockRejectedValue(reject)
      : vi.fn().mockResolvedValue(stream),
  };
}

describe('useVoiceRecorder (Round 4 T4.2)', () => {
  const originalFetch = globalThis.fetch;
  const originalMediaDevices = (navigator as { mediaDevices?: unknown }).mediaDevices;

  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    // 始终 delete — jsdom 默认就没 MediaRecorder;测试 1 装过,后续测试不能继承
    delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
    if (originalMediaDevices === undefined) {
      // jsdom 没有 mediaDevices,无需清理
    } else {
      Object.defineProperty(navigator, 'mediaDevices', {
        value: originalMediaDevices,
        configurable: true,
      });
    }
    vi.restoreAllMocks();
  });

  it('happy path:start → stop → fetch /api/asr → onTranscribed(回文本)', async () => {
    const stream = makeFakeStream();
    const recorder: MediaRecorderMock = {
      start: vi.fn(),
      stop: vi.fn(),
      ondataavailable: null,
      onstop: null,
      onerror: null,
      mimeType: '',
    };
    installMediaRecorderMock(recorder);
    installGetUserMediaMock(stream);

    const onTranscribed = vi.fn();
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ text: '今天行情如何' }),
      text: async () => '{"text":"今天行情如何"}',
    });
    globalThis.fetch = fetchMock as unknown as typeof fetch;

    const { result } = renderHook(() => useVoiceRecorder({ onTranscribed }));

    await act(async () => {
      await result.current.start();
    });
    expect(result.current.state).toBe('recording');
    expect(recorder.start).toHaveBeenCalledTimes(1);

    await act(async () => {
      await result.current.stop();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain('/api/asr');
    // FormData 验证:从 init.body 拿 FormData,append('audio', ...) 是 blob
    const form = init?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('audio')).toBeInstanceOf(Blob);

    expect(onTranscribed).toHaveBeenCalledWith('今天行情如何');
    expect(result.current.state).toBe('idle');
    expect(result.current.error).toBeNull();
  });

  it('权限拒绝:getUserMedia throws NotAllowedError → state=error + 友好文案', async () => {
    // 必须先装 MediaRecorder mock,否则 isMediaRecorderSupported() 早退
    // 走"不支持"分支,永远到不了 catch。recorder 字段没关系,反正 getUserMedia
    // 拒绝后 hook 不会走到 new MediaRecorder。
    const recorder: MediaRecorderMock = {
      start: vi.fn(),
      stop: vi.fn(),
      ondataavailable: null,
      onstop: null,
      onerror: null,
      mimeType: '',
    };
    installMediaRecorderMock(recorder);
    const denied = new Error('Permission denied by user');
    denied.name = 'NotAllowedError';
    installGetUserMediaMock(makeFakeStream(), denied);

    const onTranscribed = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onTranscribed }));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.state).toBe('error');
    expect(result.current.error).toMatch(/麦克风权限被拒绝/);
    expect(onTranscribed).not.toHaveBeenCalled();
  });

  it('不支持环境:MediaRecorder 未定义 → start() 直接 error,不调 getUserMedia', async () => {
    delete (globalThis as { MediaRecorder?: unknown }).MediaRecorder;
    // 即使装了 getUserMedia 也不该被调
    installGetUserMediaMock(makeFakeStream());

    const onTranscribed = vi.fn();
    const { result } = renderHook(() => useVoiceRecorder({ onTranscribed }));

    await act(async () => {
      await result.current.start();
    });

    expect(result.current.state).toBe('error');
    expect(result.current.error).toMatch(/不支持/);
    expect(onTranscribed).not.toHaveBeenCalled();
  });

  it('空录音(0 chunks)→ 不调 fetch,直接回 idle,onTranscribed 不触发', async () => {
    const stream = makeFakeStream();
    const recorder: MediaRecorderMock = {
      start: vi.fn(),
      stop: vi.fn(),
      ondataavailable: null,
      onstop: null,
      onerror: null,
      mimeType: '',
    };
    // 先装 install(它会写 recorder.stop = vi.fn(() => ondataavailable + onstop)),
    // 装完之后**再**覆盖 stop — install 内联赋值在 mock class 构造前,
    // mock class 构造时 `this.stop = () => recorder.stop()` 是按引用读的,
    // 后续给 recorder.stop 重新赋值,hook 调到 class 实例的 stop → 闭包读
    // 检索 recorder.stop → 拿到新值(不触发 ondataavailable)。
    installMediaRecorderMock(recorder);
    recorder.stop = vi.fn(() => {
      // 显式不触发 ondataavailable,只 resolve onstop
      if (recorder.onstop) recorder.onstop();
    });
    installGetUserMediaMock(stream);

    const fetchMock = vi.fn();
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const onTranscribed = vi.fn();

    const { result } = renderHook(() => useVoiceRecorder({ onTranscribed }));

    await act(async () => {
      await result.current.start();
    });
    // start 调了 recorder.start,但没触发 ondataavailable → chunks 应为空
    await act(async () => {
      await result.current.stop();
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(onTranscribed).not.toHaveBeenCalled();
    expect(result.current.state).toBe('idle');
    expect(result.current.error).toBeNull();
  });
});