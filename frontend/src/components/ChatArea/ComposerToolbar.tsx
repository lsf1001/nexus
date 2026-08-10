/**
 * Composer 左侧工具条:附件 / 思考开关 / 风格选择器。
 *
 * 附件按钮由父组件 Composer 注入 onAttach 回调接成 file picker;
 * 不传 onAttach 时按钮退化为占位(aria-disabled),保持向后兼容。
 * 类名双挂:`composer-plus` 是测试锁定的结构类名,`composer-attach-btn`
 * 承载 chat.css 里的圆形描边样式(两者都不能删)。
 *
 * 思考开关:绑定 store 顶层 showThinking(来自 uiPrefs 切片)。
 *
 * 风格选择器(Round 6.1 Task 9 改造):
 * - 原版:本地 useState,UI-only,未下发后端
 * - 现版:接 store.sessionStyles[sid] + 乐观更新(同步 setSessionStyle),
 *   同步调 apiPatch(`/api/sessions/${sid}`, { style })。失败时 store 回滚 +
 *   console.error,避免 UI 与后端不一致时用户无法察觉。
 * - sessionId 由父级 Composer 注入(与 conversationId 链路对齐),store
 *   不引入 activeSessionId 全局态(避免冗余)。
 * - 触发器旁加 style-badge 徽标:当前风格为 default 时不显示,简洁/专业时
 *   显示对应 label,作为当前回复风格的可视锚点。
 *
 * WHY 双写 + 回滚:store 同步让 UI 立即反馈(乐观更新),PATCH 失败时 store
 * 回滚给用户明显错误反馈,跟一般 SPA mutation 模式一致。后端 422(非法
 * style)/404(session 不存在)/500 等都会走这条路径。
 */
import type { JSX } from 'react';
import { Plus, Brain, Lightbulb, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu';
import { useStore } from '../../store';
import { apiPatch } from '../../lib/api';
import { cn } from '@/lib/utils';
import type { StyleOption } from '../../types';

/** UI 显示标签映射 — 单一来源,trigger label / menu item / 徽标共用 */
const STYLE_LABELS: Record<StyleOption, string> = {
  default: '默认',
  concise: '简洁',
  professional: '专业',
};
const STYLE_VALUES: readonly StyleOption[] = [
  'default',
  'concise',
  'professional',
];

interface ComposerToolbarProps {
  /** 附件 file picker 回调;未传时按钮退化为占位 */
  onAttach?: () => void;
  /**
   * 当前会话 id — 风格选择器用它在 store.sessionStyles 定位当前风格,
   * 并把 PATCH 路径拼成 `/api/sessions/${sessionId}`。必传(父级 Composer
   * 从 conversationId 透传);不传时风格选择器退化为只读(显示 '默认')。
   */
  sessionId?: string;
}

export function ComposerToolbar({
  onAttach,
  sessionId,
}: ComposerToolbarProps = {}): JSX.Element {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const sessionStyles = useStore((s) => s.sessionStyles);
  const setSessionStyle = useStore((s) => s.setSessionStyle);

  /** 当前风格:无 sessionId 时退化为 default(纯 UI 占位) */
  const currentStyle: StyleOption = sessionId
    ? (sessionStyles[sessionId] ?? 'default')
    : 'default';

  /**
   * 切换风格 — 乐观更新 + PATCH + 失败回滚。
   *
   * WHY:UI 立即反映用户意图;PATCH 失败时把 store 还原,避免后端最终
   * 未持久化但前端已显示"专业"的飘移;rollback 用闭包捕获 prevStyle
   * 而不是重读 store,免去额外选择器订阅。
   */
  const handleSelect = (next: StyleOption): void => {
    if (!sessionId) return;
    const prevStyle = sessionStyles[sessionId] ?? 'default';
    if (prevStyle === next) return;
    setSessionStyle(sessionId, next);
    apiPatch(`/api/sessions/${sessionId}`, { style: next }).catch((err) => {
      // 回滚 + 日志:失败通常是 422 / 404 / 5xx;不影响下次切换重试。
      setSessionStyle(sessionId, prevStyle);
      console.error(
        `[ComposerToolbar] 风格更新失败 sid=${sessionId} style=${next}:`,
        err,
      );
    });
  };

  const currentLabel = STYLE_LABELS[currentStyle];
  const showBadge = currentStyle !== 'default';

  return (
    <div className="composer-toolbar flex items-center gap-1">
      {/* 附件按钮:父组件传 onAttach 时 → 真触发 file picker;
          未传 → 占位按钮(aria-disabled),保持向后兼容 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn('composer-plus', 'composer-attach-btn')}
            aria-label={onAttach ? '上传附件' : '添加附件 / 截图 / 选 skill'}
            aria-disabled={onAttach ? undefined : 'true'}
            tabIndex={onAttach ? undefined : -1}
            onClick={onAttach ?? (() => {
              /* 占位:无行为,后续 PR 接入上传 / 截图 / skill 选择 */
            })}
          >
            <Plus />
          </Button>
        </TooltipTrigger>
        <TooltipContent>{onAttach ? '上传附件' : '附件 / 截图 / 选 skill（即将开放）'}</TooltipContent>
      </Tooltip>

      {/* 思考开关:绑定 store 顶层 showThinking */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant={showThinking ? 'secondary' : 'ghost'}
            size="icon"
            aria-pressed={showThinking}
            aria-label="切换思考过程显示"
            onClick={() => setShowThinking(!showThinking)}
          >
            {showThinking ? <Brain /> : <Lightbulb />}
          </Button>
        </TooltipTrigger>
        <TooltipContent>思考过程：{showThinking ? '开启' : '关闭'}</TooltipContent>
      </Tooltip>

      {/* 风格选择器:Round 6.1 改造后接 store + PATCH + 徽标 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1 text-xs text-muted-foreground"
            aria-label="选择回复风格"
          >
            {currentLabel}
            {showBadge ? (
              <span
                className="style-badge ml-1 rounded-full bg-secondary px-1.5 py-0.5 text-[10px] font-medium text-secondary-foreground"
                aria-hidden="true"
              >
                {currentLabel}
              </span>
            ) : null}
            <ChevronDown className="size-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {STYLE_VALUES.map((value) => {
            const label = STYLE_LABELS[value];
            return (
              <DropdownMenuItem
                key={value}
                onSelect={() => handleSelect(value)}
                aria-checked={currentStyle === value}
              >
                {label}
              </DropdownMenuItem>
            );
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}