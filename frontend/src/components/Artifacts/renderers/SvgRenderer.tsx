/**
 * SVG 渲染器 — 内联 SVG, fit width(SPEC §8.4)
 *
 * - viewBox 自适应面板宽度
 * - 最大宽度 = 面板宽度 - 28px padding, 垂直居中
 * - 解析失败 → <pre> + "SVG 解析失败"
 */
import { useMemo } from 'react';

export interface SvgRendererProps {
  content: string;
}

export function SvgRenderer({ content }: SvgRendererProps) {
  // 抽取 <svg ...>...</svg> 块
  const svgMarkup = useMemo(() => extractSvg(content), [content]);

  if (!svgMarkup) {
    return (
      <div className="artifact-renderer artifact-renderer-svg is-error">
        <pre>{content}</pre>
        <div className="artifact-renderer-error-tag">SVG 解析失败</div>
      </div>
    );
  }

  return (
    <div
      className="artifact-renderer artifact-renderer-svg"
      // SVG 字符串来自工具结果,信任工具(不直接 dangerouslySetInnerHTML 用户输入)
      dangerouslySetInnerHTML={{ __html: svgMarkup }}
    />
  );
}

function extractSvg(content: string): string | null {
  const match = content.match(/<svg\b[\s\S]*?<\/svg>/i);
  return match ? match[0] : null;
}