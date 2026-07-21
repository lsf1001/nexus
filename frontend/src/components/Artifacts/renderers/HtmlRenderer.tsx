/**
 * HTML 渲染器 — sandboxed iframe(SPEC §8.5)
 *
 * - sandbox="allow-scripts"(禁止 allow-same-origin 防提权)
 * - srcDoc 直接内联文档
 * - 顶部小字提示 + ↻ 重新加载
 * - loading="lazy"
 */
import { useMemo, useState } from 'react';

export interface HtmlRendererProps {
  content: string;
}

export function HtmlRenderer({ content }: HtmlRendererProps) {
  // 用 reload 计数触发 srcDoc 重渲
  const [reloadKey, setReloadKey] = useState(0);
  const srcDoc = useMemo(() => withSandbox(content), [content]);

  return (
    <div className="artifact-renderer artifact-renderer-html">
      <div className="artifact-html-toolbar">
        <span className="artifact-html-info">sandbox · console 隔离</span>
        <button
          type="button"
          className="artifact-html-reload"
          onClick={() => setReloadKey((k) => k + 1)}
          aria-label="重新加载 HTML 产物"
        >
          ↻ 重新加载
        </button>
      </div>
      <iframe
        key={reloadKey}
        title="artifact-html-preview"
        sandbox="allow-scripts"
        srcDoc={srcDoc}
        loading="lazy"
        className="artifact-html-iframe"
      />
    </div>
  );
}

/** 包裹最小 HTML 骨架(sandbox 不继承父页样式) */
function withSandbox(raw: string): string {
  const trimmed = raw.trim();
  if (/<html[\s>]/i.test(trimmed)) return trimmed;
  return `<!doctype html><html><head><meta charset="utf-8"><style>
    body { font: 14px -apple-system, "PingFang SC", sans-serif; padding: 16px; margin: 0; color: #1f1f1f; background: #fff; }
    button { cursor: pointer; }
  </style></head><body>${trimmed}</body></html>`;
}