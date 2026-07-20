/**
 * Markdown 渲染器 — react-markdown + remark-gfm(SPEC §8.3)
 *
 * 继承 .prose 既有样式(标题 / 段落 / 列表 / 行内 code / pre 块)。
 */
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

export interface MarkdownRendererProps {
  content: string;
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  return (
    <div className="artifact-renderer artifact-renderer-markdown prose">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}