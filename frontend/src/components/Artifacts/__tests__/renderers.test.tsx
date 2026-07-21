import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { CodeRenderer } from '../renderers/CodeRenderer';
import { MarkdownRenderer } from '../renderers/MarkdownRenderer';
import { SvgRenderer } from '../renderers/SvgRenderer';
import { HtmlRenderer } from '../renderers/HtmlRenderer';

describe('CodeRenderer', () => {
  it('渲染行号 + 高亮容器', () => {
    const { container } = render(<CodeRenderer content={'print("hi")\nprint("two")'} language="python" />);
    const root = container.querySelector('.artifact-renderer-code');
    expect(root).toBeTruthy();
    const lines = container.querySelectorAll('.artifact-code-line');
    expect(lines.length).toBe(2);
    // 行号
    expect(lines[0]?.querySelector('.artifact-code-line-num')?.textContent).toBe('1');
    expect(lines[1]?.querySelector('.artifact-code-line-num')?.textContent).toBe('2');
    // 语言标识
    expect(container.querySelector('.artifact-code-lang')?.textContent).toBe('python');
  });

  it('未知语言退化为纯文本(不抛错)', () => {
    const { container } = render(<CodeRenderer content="plain" language="不存在" />);
    expect(container.querySelector('.artifact-renderer-code')).toBeTruthy();
    // 不抛错 + 渲染 1 行
    expect(container.querySelectorAll('.artifact-code-line')).toHaveLength(1);
  });
});

describe('MarkdownRenderer', () => {
  it('渲染标题 / 列表 / 行内 code', () => {
    const md = '# 标题\n\n- item1\n- item2\n\n`inline`';
    const { container } = render(<MarkdownRenderer content={md} />);
    const root = container.querySelector('.artifact-renderer-markdown');
    expect(root).toBeTruthy();
    expect(root?.querySelector('h1')?.textContent).toBe('标题');
    expect(root?.querySelectorAll('li').length).toBe(2);
    expect(root?.querySelector('code')?.textContent).toBe('inline');
  });
});

describe('SvgRenderer', () => {
  it('抽取并内联 svg', () => {
    const svg = '<svg viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>';
    const { container } = render(<SvgRenderer content={svg} />);
    const root = container.querySelector('.artifact-renderer-svg');
    expect(root).toBeTruthy();
    expect(root?.querySelector('svg')).toBeTruthy();
    expect(root?.querySelector('circle')).toBeTruthy();
  });

  it('非 svg 内容显示错误标签', () => {
    const { container } = render(<SvgRenderer content={'hello world this is not svg'} />);
    const root = container.querySelector('.artifact-renderer-svg.is-error');
    expect(root).toBeTruthy();
    expect(container.querySelector('.artifact-renderer-error-tag')?.textContent).toContain('SVG 解析失败');
  });
});

describe('HtmlRenderer', () => {
  it('渲染 sandbox iframe + 重新加载按钮', () => {
    const html = '<button>点我</button>';
    const { container } = render(<HtmlRenderer content={html} />);
    const root = container.querySelector('.artifact-renderer-html');
    expect(root).toBeTruthy();
    const iframe = root?.querySelector('iframe');
    expect(iframe).toBeTruthy();
    expect(iframe?.getAttribute('sandbox')).toBe('allow-scripts');
    expect(iframe?.getAttribute('sandbox')).not.toContain('allow-same-origin');
    expect(container.querySelector('.artifact-html-reload')?.textContent).toContain('重新加载');
  });

  it('纯片段自动包 html 骨架', () => {
    const { container } = render(<HtmlRenderer content="<p>hi</p>" />);
    const iframe = container.querySelector('iframe') as HTMLIFrameElement | null;
    expect(iframe?.srcdoc).toMatch(/^<!doctype html>/i);
    expect(iframe?.srcdoc).toContain('<p>hi</p>');
  });
});