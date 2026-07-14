/**
 * remarkPathLinkify 单测 — 2026-07-14 用户截图反馈:
 *   LLM 输出 /Users/.../koi.jpg 等本地路径,前端只显示纯文本,
 *   没法点击在 Preview.app 里打开。
 *
 * 覆盖 4 类路径:
 *  1. **图片后缀**(jpg/png/gif/webp/bmp/svg) → 转 image AST 节点
 *  2. **其他路径**(无后缀 / .txt / .log) → 转 link AST 节点(href=file://)
 *  3. **inlineCode / code block** 内部不转(尊重原文,不被链接污染)
 *  4. **已有 link / 纯文本里的相对路径** 不动(只匹配绝对路径)
 *
 * 测试方式:把 markdown 走 unified 解析 → 走我们的插件 → 走 mdast-util-to-hast
 * → 检查生成 HTML 是否含 <a href="file://..."> 与 <img src="file://...">。
 */

import { describe, expect, it } from 'vitest';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkRehype from 'remark-rehype';
import { remarkPathLinkify } from '../remarkPathLinkify';

function render(md: string): string {
  const tree = unified().use(remarkParse).use(remarkPathLinkify).parse(md);
  // 跑我们的插件(必须用 Processor 跑,直接 parse 不会跑 plugin)
  unified().use(remarkParse).use(remarkPathLinkify).runSync(tree);
  const hast = unified().use(remarkRehype).runSync(tree);
  // hast → 简化 HTML(只为断言,无须 rehype-stringify 完整管线)
  return hastToHtml(hast as { type: string; children?: unknown[]; value?: string; tagName?: string; properties?: Record<string, unknown> });
}

function hastToHtml(node: { type: string; children?: unknown[]; value?: string; tagName?: string; properties?: Record<string, unknown> }): string {
  if (node.type === 'text') return escapeHtml(node.value ?? '');
  if (node.type === 'element') {
    const props = node.properties ?? {};
    const attrs = Object.entries(props)
      .map(([k, v]) => ` ${k}="${escapeAttr(String(v))}"`)
      .join('');
    const inner = (node.children ?? []).map((c) => hastToHtml(c as Parameters<typeof hastToHtml>[0])).join('');
    return `<${node.tagName}${attrs}>${inner}</${node.tagName}>`;
  }
  if (node.type === 'root' && node.children) {
    return node.children.map((c) => hastToHtml(c as Parameters<typeof hastToHtml>[0])).join('');
  }
  return '';
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!));
}
function escapeAttr(s: string): string {
  return s.replace(/"/g, '&quot;');
}

describe('remarkPathLinkify', () => {
  it('图片后缀路径 → 转 <img src="file://...">', () => {
    const html = render('图片在 /Users/yxb/.nexus/outputs/koi_20260714_180037.jpg');
    expect(html).toContain('<img');
    expect(html).toContain('src="file:///Users/yxb/.nexus/outputs/koi_20260714_180037.jpg"');
    expect(html).toContain('alt="/Users/yxb/.nexus/outputs/koi_20260714_180037.jpg"');
  });

  it('非图片路径 → 转 <a href="file://..."> 节点(class 由 ChatBubble components 注入,这里只验 href + title)', () => {
    const html = render('日志写到 /Users/yxb/.nexus/outputs/run.log');
    expect(html).toContain('<a href="file:///Users/yxb/.nexus/outputs/run.log"');
    // title 由插件设(path),方便 hover 看到完整路径
    expect(html).toContain('title="/Users/yxb/.nexus/outputs/run.log"');
    // 链接文本应是路径本身
    expect(html).toMatch(/<a [^>]*>\/Users\/yxb\/.nexus\/outputs\/run\.log<\/a>/);
  });

  it('inlineCode 内部不转(保留 code span)', () => {
    const html = render('代码里出现 `/Users/yxb/x.jpg` 不应被链接');
    // 不应有 file://
    expect(html).not.toContain('file://');
    // 应有 <code>
    expect(html).toContain('<code>');
    expect(html).toContain('/Users/yxb/x.jpg');
  });

  it('相对路径 / 单词不误转', () => {
    const html = render('看 users/x.jpg 这种相对路径不要动');
    expect(html).not.toContain('file://');
    expect(html).toContain('users/x.jpg');
  });

  it('混合文本: 路径前后中文标点保留', () => {
    const html = render('打开 /Users/yxb/.nexus/outputs/photo.png 看效果。');
    expect(html).toContain('src="file:///Users/yxb/.nexus/outputs/photo.png"');
    // 句末中文句号应保留(没被吞进 image alt)
    expect(html).toContain('效果');
    expect(html).toContain('。');
  });

  it('多个路径同时出现(贪心关闭,各转各的)', () => {
    const html = render('两图: /Users/yxb/a.jpg 和 /Users/yxb/b.png');
    const matches = html.match(/<img /g) ?? [];
    expect(matches.length).toBe(2);
  });
});