/**
 * Code 渲染器 — 行号 + highlight.js 语法高亮(SPEC §8.2)
 *
 * - 行号列宽 24px 右对齐 var(--ink-3)
 * - 主题按 data-theme 切(github / github-dark)
 * - 长行 <pre> 内部横向滚动
 * - 字体 var(--font-mono), 字号 12.5px, 行高 1.55
 */
import { useEffect, useMemo, useRef } from 'react';
import hljs from 'highlight.js/lib/core';

// 提前按需注册常用语言,避免全量打包
import python from 'highlight.js/lib/languages/python';
import typescript from 'highlight.js/lib/languages/typescript';
import javascript from 'highlight.js/lib/languages/javascript';
import json from 'highlight.js/lib/languages/json';
import bash from 'highlight.js/lib/languages/bash';
import xml from 'highlight.js/lib/languages/xml';
import css from 'highlight.js/lib/languages/css';
import markdown from 'highlight.js/lib/languages/markdown';
import yaml from 'highlight.js/lib/languages/yaml';
import sql from 'highlight.js/lib/languages/sql';
import go from 'highlight.js/lib/languages/go';
import rust from 'highlight.js/lib/languages/rust';
import java from 'highlight.js/lib/languages/java';
import ruby from 'highlight.js/lib/languages/ruby';
import cpp from 'highlight.js/lib/languages/cpp';

import 'highlight.js/styles/github.css';
import 'highlight.js/styles/github-dark.css';

let registered = false;
function ensureRegistered(): void {
  if (registered) return;
  hljs.registerLanguage('python', python);
  hljs.registerLanguage('typescript', typescript);
  hljs.registerLanguage('tsx', typescript);
  hljs.registerLanguage('javascript', javascript);
  hljs.registerLanguage('jsx', javascript);
  hljs.registerLanguage('json', json);
  hljs.registerLanguage('bash', bash);
  hljs.registerLanguage('xml', xml);
  hljs.registerLanguage('html', xml);
  hljs.registerLanguage('css', css);
  hljs.registerLanguage('markdown', markdown);
  hljs.registerLanguage('yaml', yaml);
  hljs.registerLanguage('sql', sql);
  hljs.registerLanguage('go', go);
  hljs.registerLanguage('rust', rust);
  hljs.registerLanguage('java', java);
  hljs.registerLanguage('ruby', ruby);
  hljs.registerLanguage('cpp', cpp);
  hljs.registerLanguage('c', cpp);
  registered = true;
}

export interface CodeRendererProps {
  content: string;
  language?: string;
}

export function CodeRenderer({ content, language }: CodeRendererProps) {
  const ref = useRef<HTMLElement>(null);

  const highlighted = useMemo(() => {
    ensureRegistered();
    if (language && hljs.getLanguage(language)) {
      try {
        return hljs.highlight(content, { language, ignoreIllegals: true }).value;
      } catch {
        /* fall through */
      }
    }
    return escapeHtml(content);
  }, [content, language]);

  // 主题跟随 data-theme(highlight.js 用 pre/code.hljs class)
  useEffect(() => {
    if (!ref.current) return;
    ref.current.classList.add('hljs');
  }, []);

  const lines = highlighted.split('\n');

  return (
    <div className="artifact-renderer artifact-renderer-code">
      <div className="artifact-code-meta">
        {language && <span className="artifact-code-lang">{language}</span>}
      </div>
      <pre className="artifact-code-pre">
        <code ref={ref} className="hljs" data-theme-sync="true">
          {lines.map((line, i) => (
            <span key={i} className="artifact-code-line">
              <span className="artifact-code-line-num">{i + 1}</span>
              <span
                className="artifact-code-line-content"
                // 高亮 HTML 来自 highlight.js, 内容受信任(我们自己 highlight 出来的)
                dangerouslySetInnerHTML={{ __html: line || '&nbsp;' }}
              />
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}