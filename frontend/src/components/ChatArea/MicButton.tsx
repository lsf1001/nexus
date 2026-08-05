/**
 * Round 4 Task 4.2:Composer 旁的麦克风按钮。
 *
 * 三态视觉:
 *   idle    → 🎤 Mic icon,默认 ghost 样式,点击开始录音
 *   recording→ 🔴 Square icon + 红色脉冲 + 计时数字,点击停止录音
 *   transcribing → ⏳ Loader2 spinner(不可点),后台把 webm 提交到 /api/asr
 *   error   → ⚠️ AlertTriangle icon + 红色 tooltip 提示,自动回归 idle(下次点重试)
 *
 * 状态机 + 错误处理全交给 useVoiceRecorder;本组件只负责:
 *   1. 调用 hook
 *   2. 把转写文本回填到 Composer(value + onChange)
 *   3. 渲染对应 icon + tooltip
 *
 * WHY 不放 ComposerToolbar:Toolbar 只接 onAttach 一个回调,
 * 把 onTranscribed(text) 也塞进去会让 Toolbar 知道 textarea state,
 * 拆开更好测(MicButton 单测不依赖 ComposerToolbar 上下文)。
 */

import { Mic, Square, Loader2, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import { useVoiceRecorder, isMediaRecorderSupported } from '@/hooks/useVoiceRecorder';

export interface MicButtonProps {
  /** 转写成功后文本如何回填到 Composer(等价于 textarea onChange) */
  onTranscribed: (text: string) => void;
  /** 录音模式开关:false 时按钮 aria-disabled,常用于离线 / 无 LLM 时 */
  enabled?: boolean;
  /** 自定义 className,父容器可追加间距 */
  className?: string;
}

/** 录音中红色脉冲样式 — 跟 Tailwind ring pulse 不同(避免动画 GPU 开销) */
const RECORDING_CLASS = 'mic-button-recording';

export function MicButton({ onTranscribed, enabled = true, className }: MicButtonProps) {
  const { state, elapsedSec, error, start, stop } = useVoiceRecorder({ onTranscribed });

  const handleClick = (): void => {
    if (state === 'recording') {
      void stop();
    } else if (state === 'idle' || state === 'error') {
      void start();
    }
    // transcribing → 不可点
  };

  // 不可用环境直接退化成 ghost 按钮 + tooltip 解释
  const supported = isMediaRecorderSupported();
  const disabled = !enabled || !supported || state === 'transcribing';

  const tooltip = (() => {
    if (!supported) return '当前环境不支持麦克风录音';
    if (!enabled) return '离线模式暂不可用';
    if (state === 'recording') return `录音中 · ${elapsedSec}s,点击停止`;
    if (state === 'transcribing') return '正在转写…';
    if (state === 'error') return error ?? '录音失败,点击重试';
    return '语音输入';
  })();

  const icon = (() => {
    if (state === 'transcribing') return <Loader2 className="animate-spin" />;
    if (state === 'recording') return <Square aria-hidden />;
    if (state === 'error') return <AlertTriangle aria-hidden />;
    return <Mic aria-hidden />;
  })();

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant={state === 'recording' ? 'destructive' : 'ghost'}
          size="icon"
          className={cn('mic-button', state === 'recording' && RECORDING_CLASS, className)}
          aria-label={
            state === 'recording'
              ? `停止录音 · ${elapsedSec}s`
              : state === 'transcribing'
                ? '正在转写'
                : '开始语音输入'
          }
          aria-pressed={state === 'recording'}
          disabled={disabled}
          onClick={handleClick}
          data-state={state}
        >
          {icon}
          {state === 'recording' && (
            <span className="mic-button-elapsed" aria-hidden>
              {elapsedSec}
            </span>
          )}
        </Button>
      </TooltipTrigger>
      <TooltipContent>{tooltip}</TooltipContent>
    </Tooltip>
  );
}