/**
 * Artifact 推断工具 — SPEC §5.1
 *
 * ToolCallCard 的 args.path + result 文本 → { kind, language, filename }。
 * 推断失败 → kind='code' language 由 caller 决定 fallback。
 */

import type { ArtifactKind } from '../../../store/slices/artifacts';

const EXT_LANG: Record<string, string> = {
  py: 'python',
  ts: 'typescript',
  tsx: 'tsx',
  js: 'javascript',
  jsx: 'jsx',
  json: 'json',
  css: 'css',
  scss: 'scss',
  html: 'xml',
  htm: 'xml',
  xml: 'xml',
  svg: 'xml',
  md: 'markdown',
  markdown: 'markdown',
  sh: 'bash',
  bash: 'bash',
  yml: 'yaml',
  yaml: 'yaml',
  sql: 'sql',
  go: 'go',
  rs: 'rust',
  java: 'java',
  rb: 'ruby',
  c: 'c',
  cpp: 'cpp',
  h: 'c',
  hpp: 'cpp',
};

const WHITELIST_TOOLS = new Set([
  'edit_file',
  'write_md',
  'write_file',
  'draw_diagram',
  'write_html',
  'create_file',
  'save_file',
]);

/** 工具名是否值得联动到 Artifacts */
export function isArtifactTool(name: string): boolean {
  return WHITELIST_TOOLS.has(name);
}

/** 从路径/文件名取后缀(无点) */
function extOf(path: string): string {
  const m = path.match(/\.([a-z0-9]+)$/i);
  return m?.[1]?.toLowerCase() ?? '';
}

function baseOf(path: string): string {
  const m = path.match(/([^/\\]+)$/);
  return m?.[1] ?? path;
}

export interface InferResult {
  kind: ArtifactKind;
  language?: string;
  filename: string;
}

/**
 * 推断 artifact 三元组。
 * - .md / .markdown → markdown
 * - .svg 且 content 以 <svg 开头 → svg
 * - .html / .htm 且 content 以 < 开头 → html
 * - 其他 → code + 语言从后缀取
 */
export function inferArtifact(
  toolName: string,
  args: Record<string, unknown> | undefined,
  result: string | undefined,
): InferResult | null {
  if (!args || !result) return null;
  if (!isArtifactTool(toolName)) return null;
  if (result.length < 30) return null;

  // 找 path / file / filename 任一字段
  const rawPath =
    (typeof args.path === 'string' && args.path) ||
    (typeof args.file === 'string' && args.file) ||
    (typeof args.filename === 'string' && args.filename) ||
    '';
  if (!rawPath) return null;

  const ext = extOf(rawPath);
  const filename = baseOf(rawPath);

  // markdown
  if (ext === 'md' || ext === 'markdown') {
    return { kind: 'markdown', filename };
  }

  // svg(优先看扩展,再 fallback 看内容前缀)
  if (ext === 'svg') {
    return { kind: 'svg', filename };
  }

  // html
  if (ext === 'html' || ext === 'htm') {
    return { kind: 'html', filename, language: EXT_LANG[ext] };
  }

  // code:取语言,失败就 undefined(高亮会 fallback 到 plain)
  const language = EXT_LANG[ext];
  return { kind: 'code', filename, language };
}