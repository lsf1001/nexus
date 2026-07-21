import { useState } from 'react';
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
import { cn } from '@/lib/utils';

/** 风格选项(本期 UI-only,未下发后端) */
const STYLE_OPTIONS = ['默认', '简洁', '专业'] as const;
type StyleOption = (typeof STYLE_OPTIONS)[number];

/**
 * Composer 左侧工具条:附件占位 / 思考开关 / 风格选择器。
 *
 * 当前均为 UI-only:
 *   - 附件:占位按钮,本期不接真实上传 / 截图 / skill 选择。
 *   - 思考开关:绑定 store 顶层 showThinking(来自 uiPrefs 切片)。
 *   - 风格选择器:本地 state 驱动,仅改 UI。
 * // TODO: wire to backend style param(将 style 作为请求参数下发)。
 */
export function ComposerToolbar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);
  const [style, setStyle] = useState<StyleOption>('默认');

  return (
    <div className="composer-toolbar flex items-center gap-1">
      {/* 附件占位:本期不接真实上传,无点击行为 */}
      <Tooltip>
        <TooltipTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className={cn('composer-plus')}
            aria-label="添加附件 / 截图 / 选 skill"
            aria-disabled="true"
            tabIndex={-1}
            onClick={() => {
              /* 占位:无行为,后续 PR 接入上传 / 截图 / skill 选择 */
            }}
          >
            <Plus />
          </Button>
        </TooltipTrigger>
        <TooltipContent>附件 / 截图 / 选 skill（即将开放）</TooltipContent>
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

      {/* 风格选择器:UI-only,本地 state 驱动 */}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="gap-1 text-xs text-muted-foreground"
            aria-label="选择回复风格"
          >
            {style}
            <ChevronDown className="size-3.5" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {STYLE_OPTIONS.map((opt) => (
            <DropdownMenuItem key={opt} onSelect={() => setStyle(opt)}>
              {opt}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
