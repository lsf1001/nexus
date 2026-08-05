/**
 * Round 4 Task 4.2:浏览器侧麦克风录音 hook。
 *
 * 状态机:
 *   idle ──start()──▶ recording ──stop()──▶ transcribing ──▶ idle
 *                                  │
 *                                  └──▶ error(media 或 asr 失败)
 *
 * 实现要点:
 *   - getUserMedia({ audio: true }):浏览器原生,Tauri 2 WKWebView 默认支持
 *     (前提是 Info.plist 已声明 NSMicrophoneUsageDescription)
 *   - MediaRecorder 选 audio/webm;Safari 旧版可能不支持,本轮仅 Chrome / Tauri webview
 *   - stop() 后合并 chunks → Blob → FormData → POST /api/asr
 *   - CSP 已允许 media-src 'self' data: blob: 和 connect-src 同源 /
 *     ws / wss;录音产物 blob URL + fetch 同源都通畅
 *
 * 错误处理:
 *   - NotAllowedError:用户拒绝麦克风权限(系统级 / 浏览器级)
 *   - NotFoundError:无麦克风设备
 *   - 服务器返回 4xx / 5xx:错误信息透传给上层(MicButton 显示)
 *
 * 不做的事:
 *   - 实时流式识别(只录完整一段再转写,YAGNI)
 *   - 多语言检测 / VAD(等真实需求)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../lib/api';

export type VoiceRecorderState = 'idle' | 'recording' | 'transcribing' | 'error';

export interface UseVoiceRecorderOpts {
  /** 转写成功后回调(收到纯文本) */
  onTranscribed: (text: string) => void;
}

export interface UseVoiceRecorderReturn {
  state: VoiceRecorderState;
  /** 累计录音时长(秒),仅 recording 中变化 */
  elapsedSec: number;
  error: string | null;
  start: () => Promise<void>;
  stop: () => Promise<void>;
}

/** 浏览器/Safari 不支持 MediaRecorder 时(Mac < 14),上层可降级。 */
export function isMediaRecorderSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    typeof window.MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

/** 选浏览器最支持的 audio mime;失败回退空串让浏览器给默认。 */
function pickAudioMime(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];
  for (const m of candidates) {
    if (MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

export function useVoiceRecorder(opts: UseVoiceRecorderOpts): UseVoiceRecorderReturn {
  const { onTranscribed } = opts;
  const [state, setState] = useState<VoiceRecorderState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [elapsedSec, setElapsedSec] = useState(0);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAtRef = useRef<number | null>(null);
  /** 防双 start 互踩;stop 完成前再次 start 直接拒绝 */
  const busyRef = useRef(false);

  /** 清流 + 释放麦克风(必须在停止后调一次,否则系统麦克风指示灯不灭) */
  const releaseStream = useCallback((): void => {
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
    }
    streamRef.current = null;
  }, []);

  /** 简单的 200ms tick,刷新 elapsedSec;停止时一并 clear */
  useEffect(() => {
    if (state !== 'recording') return;
    const id = window.setInterval(() => {
      if (startedAtRef.current != null) {
        setElapsedSec(Math.floor((Date.now() - startedAtRef.current) / 1000));
      }
    }, 200);
    return () => window.clearInterval(id);
  }, [state]);

  /** 组件卸载兜底释放。 */
  useEffect(() => {
    return () => releaseStream();
  }, [releaseStream]);

  const start = useCallback(async (): Promise<void> => {
    if (busyRef.current) return;
    if (state === 'recording' || state === 'transcribing') return;
    if (!isMediaRecorderSupported()) {
      setState('error');
      setError('当前环境不支持麦克风录音(浏览器过旧或非安全上下文)');
      return;
    }
    busyRef.current = true;
    setError(null);
    setElapsedSec(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickAudioMime();
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onerror = (e: Event) => {
        // MediaRecorderErrorEvent 的 error 字段是 DOMException
        const err = (e as unknown as { error?: Error }).error;
        setState('error');
        setError(err?.message ?? '录音失败');
        releaseStream();
      };
      recorder.start();
      startedAtRef.current = Date.now();
      setState('recording');
    } catch (err) {
      const e = err as { name?: string; message?: string };
      const name = e?.name ?? '';
      const msg = e?.message ?? String(err);
      const denied =
        name === 'NotAllowedError' ||
        name === 'SecurityError' ||
        msg.includes('Permission') ||
        msg.includes('NotAllowed');
      setState('error');
      setError(
        denied
          ? '麦克风权限被拒绝 — 请在系统设置里允许 Nexus 使用麦克风'
          : `无法访问麦克风:${msg}`,
      );
    } finally {
      busyRef.current = false;
    }
  }, [releaseStream, state]);

  const stop = useCallback(async (): Promise<void> => {
    if (state !== 'recording') return;
    if (busyRef.current) return;
    busyRef.current = true;

    const recorder = recorderRef.current;
    if (!recorder) {
      busyRef.current = false;
      return;
    }

    // 等待最后 ondataavailable + onstop;一次性把 blob 提交到 /api/asr
    const stopped = new Promise<void>((resolve) => {
      recorder.onstop = () => resolve();
    });
    recorder.stop();
    releaseStream();
    await stopped;

    const blob = new Blob(chunksRef.current, {
      type: recorder.mimeType || 'audio/webm',
    });
    chunksRef.current = [];
    startedAtRef.current = null;

    if (blob.size === 0) {
      setState('idle');
      setError(null);
      busyRef.current = false;
      return;
    }

    setState('transcribing');
    try {
      const form = new FormData();
      form.append('audio', blob, 'recording.webm');
      const res = await apiFetch('/api/asr', { method: 'POST', body: form });
      if (!res.ok) {
        const detail = (await res.text().catch(() => res.statusText)).slice(0, 200);
        throw new Error(`ASR ${res.status}: ${detail}`);
      }
      const data = (await res.json()) as { text?: string };
      const text = data.text?.trim() ?? '';
      if (text) onTranscribed(text);
      setState('idle');
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setState('error');
      setError(`转写失败:${msg}`);
    } finally {
      busyRef.current = false;
    }
  }, [onTranscribed, releaseStream, state]);

  return { state, elapsedSec, error, start, stop };
}