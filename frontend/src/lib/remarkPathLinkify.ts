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
 * 安全性:
 *   - 仅绝对路径触发,**不会**把相对路径 / 字符串里的 "users/x" 误转
 *   - file:// URL 不走 fetch,纯本地打开,无 XSS/CSRF 风险
 *   - 不解析路径合法性(前端拿不到 fs);用户点了 file:// 不存在 → OS 自己弹错
 *
 * 2026-07-14
 */
import type { Plugin } from 'unified';
import type { Root, Text, Link, Image, PhrasingContent } from 'mdast';
import { visit } from 'unist-util-visit';

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

function fileUrl(path: string): string {
  // `~` 在 file:// URL 里浏览器不展开,需转成 /Users/<user>
  if (path.startsWith('~/')) {
    // 不在浏览器侧展开 $HOME(JS 拿不到),让 OS handler 自己处理
    // macOS Electron WebView + Preview.app 对 `file://~` 不识别,故直接抛原 `~`
    return `file://${path}`;
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
        url: fileUrl(cleanPath),
        alt: cleanPath,
      };
      out.push(img);
    } else {
      const link: Link = {
        type: 'link',
        url: fileUrl(cleanPath),
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
      if (split.length === 1 && split[0].type === 'text') return;
      parent.children.splice(index, 1, ...split);
      // 跳过新插入节点(避免重复 visit 已经处理过的 link/image)
      return index + split.length;
    });
  };
};