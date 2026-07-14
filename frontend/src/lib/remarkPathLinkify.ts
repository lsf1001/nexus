/**
 * pathLinkify - 自定义 remark 插件,把聊天文本里的本地绝对路径转成可点击 link / img。
 *
 * 触发场景(用户截图 2026-07-14):
 *   LLM 用 shell_run 跑 `open /Users/.../.nexus/outputs/koi_20260714_180037.jpg`
 *   工具结果 / LLM 回复里出现绝对路径,前端 ReactMarkdown 默认只 linkify http(s)://,
 *   路径显示为纯文本,用户没法点开看图。
 *
 * 规则:
 *   - 匹配 `/Users/<...>` 或 `~/<...>` 形式的绝对路径
 *   - 路径**必须**含至少一段(至少一个 `/`)
 *   - 终结符:空白 / 行尾 / markdown 标点(`)` `]` 等)
 *   - 后缀是 .jpg/.jpeg/.png/.gif/.webp/.bmp/.svg → image 节点(前端 <img> 渲染缩略图)
 *   - 其他后缀 / 无后缀 → link 节点(file:// href,macOS 点击触发 Preview.app / Finder)
 *   - **不**触碰 inlineCode / code / link 内已有节点 — 插件只走 text node,code 是独立 AST
 *
 * Tauri 模式(2026-07-14 修):
 *   Tauri webview CSP 默认 `img-src 'self' data: blob:` 拒绝 file:// → <img> 破图。
 *   修法:Tauri 端开 assetProtocol(scope 白名单 ~/.nexus/**) + CSP 加 `asset: http://asset.localhost`;
 *   前端调 convertFileSrc(path) 把绝对路径转成 `http://asset.localhost/<encoded>`,webview 直接放行。
 *   检测方法:`window.__TAURI_INTERNALS__`(Tauri 2 注入的全局存在即在 Tauri 环境内)。
 *   浏览器模式(dev server / 非 DMG 测试)保持 file:// — browser dev 仍可点击在 Finder 里打开。
 *
 * 安全性:
 *   - 仅绝对路径触发,**不会**把相对路径 / 字符串里的 "users/x" 误转
 *   - Tauri 模式 URL 由 Tauri 自身基于配置的 scope 白名单解析,前端无法绕过 scope 访问任意路径
 *   - 不解析路径合法性(前端拿不到 fs);用户点了 file:// 不存在 → OS 自己弹错
 */
import type { Plugin } from 'unified';
import type { Root, Text, Link, Image, PhrasingContent } from 'mdast';
import { visit } from 'unist-util-visit';
import { convertFileSrc } from '@tauri-apps/api/core';

const IMAGE_EXTS = /\.(?:jpe?g|png|gif|webp|bmp|svg)(?=$|[)\]\s,，。])/i;

/**
 * 匹配 `/Users/...` 或 `~/...` 形式的本地绝对路径。
 *
 * - `~` 必须出现在行首或非标识符字符后(避免 `foo~bar`)
 * - 路径字符允许:字母 / 数字 / `/` / `_` / `-` / `.` / 空格(罕见但 macOS 允许)
 * - 终结符:空白 / 行尾 / markdown 标点 `)`, `]`, `,`, `。`, `,`
 *
 * WHY 不贪婪:一个回复里可能含多个路径,每次必须取最短命中。
 */
const PATH_RE = /(?:^|[^\w/])(?:\/Users\/[^\s)\]<>"]+|~\/[^\s)\]<>"]+)/g;

/** 检测当前是否在 Tauri webview 内(DMG 启动)。SSR/Node 环境下 window 不存在。 */
function isTauriEnv(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}

/**
 * 把本地绝对路径转成 <a href> / <img src> 可用的 URL。
 *
 * - Tauri 环境:convertFileSrc(path) → `http://asset.localhost/<encoded>`,需
 *   Tauri 端开启 assetProtocol + scope 白名单;webview CSP 已配对应放行。
 * - 浏览器环境:返回 `file://path` — macOS Chromium / Electron dev 模式下点
 *   file:// 直达 Preview / Finder。
 * - `~/...` 路径不展开(Js 拿不到 $HOME);Tauri 模式 convertFileSrc 不识别
 *   `~` 前缀,故浏览器模式才兜底 `~/`,Tauri 模式仍传原 `~/` 让 OS 报"无此文件"。
 *   (实际 LLM 输出很少出现 `~/` 路径,主要是 `/Users/...` 全路径。)
 */
function toAssetUrl(path: string): string {
  if (isTauriEnv()) {
    // convertFileSrc 是同步纯函数:返回 `http://asset.localhost/<encoded>`。
    // isTauriEnv() 在浏览器构建里被静态 false,vite dead-code-eliminate 整段;
    // Tauri 构建里才真正调用,Rust 端基于 scope 白名单解析路径。
    return convertFileSrc(path);
  }
  return `file://${path}`;
}

function splitText(text: string): PhrasingContent[] {
  const out: PhrasingContent[] = [];
  let cursor = 0;
  // 重置 lastIndex 防御(全局 RegExp 在 test 后会粘住)
  PATH_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = PATH_RE.exec(text)) !== null) {
    const fullMatch = match[0];
    const pathStart = match.index + (fullMatch.length - fullMatch.trimStart().length);
    // 跳过非路径前缀字符(空白 / 标点)
    const lead = text.slice(cursor, pathStart);
    if (lead) out.push({ type: 'text', value: lead } as Text);

    const rawPath = fullMatch.trimStart();
    const trailing = rawPath.match(/[)\].,，。]$/);
    const cleanPath = trailing ? rawPath.slice(0, -trailing[0].length) : rawPath;

    const isImage = IMAGE_EXTS.test(cleanPath);
    if (isImage) {
      const img: Image = {
        type: 'image',
        url: toAssetUrl(cleanPath),
        alt: cleanPath,
      };
      out.push(img);
    } else {
      const link: Link = {
        type: 'link',
        url: toAssetUrl(cleanPath),
        title: cleanPath,
        children: [{ type: 'text', value: cleanPath } as Text],
      };
      out.push(link);
    }

    // 把"被吞掉的尾部标点"补回去,保留原文标点
    if (trailing) {
      out.push({ type: 'text', value: trailing[0] } as Text);
    }
    cursor = pathStart + cleanPath.length + (trailing ? trailing[0].length : 0);
  }
  const tail = text.slice(cursor);
  if (tail) out.push({ type: 'text', value: tail } as Text);
  return out;
}

/**
 * remark 插件:遍历所有 text node → 切分成 text/link/image 三类节点。
 *
 * 不递归处理(只切当前 text);children of link/image 我们不动,
 * 因为它们的 url/alt 已经是结构化字段,继续改反而乱。
 */
export const remarkPathLinkify: Plugin<[], Root> = () => {
  return (tree) => {
    visit(tree, 'text', (node: Text, index, parent) => {
      if (!parent || typeof index !== 'number') return;
      const split = splitText(node.value);
      if (split.length === 0) return;
      if (split.length === 1 && split[0]?.type === 'text') return;
      parent.children.splice(index, 1, ...split);
      // 跳过新插入节点(避免重复 visit 已经处理过的 link/image)
      return index + split.length;
    });
  };
};