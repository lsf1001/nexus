/**
 * remarkPathLinkify — Tauri 模式(2026-07-14 修复 file:// CSP 被拦)。
 *
 * 背景:Tauri webview CSP 默认 `img-src 'self' data: blob:` 会拒绝 file:// URL,
 * 让 <img src="file:///..."> 显示破图占位。修法:
 *  1. Tauri 端开 assetProtocol(scope ~/.nexus/**)
 *  2. CSP img-src 加 `asset: http://asset.localhost`
 *  3. 前端 convertFileSrc(path) 产出 `http://asset.localhost/<encoded>`,webview 放行
 *
 * 测试契约:
 *  - 浏览器环境(window 无 __TAURI_INTERNALS__) → 维持 `file://` URL(向后兼容,
 *    dev mode 直接用 file:// 浏览器自动打开 + Preview)
 *  - Tauri 环境(window.__TAURI_INTERNALS__ 存在) → 转 `http://asset.localhost/...`
 *
 * 注入 mock:模拟 Tauri native bridge — `window.__TAURI_INTERNALS__.convertFileSrc`
 * 由 Rust 注入,我们把它替换成 jsdom 内的实现。这是真实路径:
 * `@tauri-apps/api/core.convertFileSrc(p)` 内部直接调
 * `window.__TAURI_INTERNALS__.convertFileSrc(p, 'asset')`,所以 mock 这个底层
 * 方法等同于测试整个调用链。
 */
import { describe, expect, it, beforeEach, afterEach } from 'vitest';

describe('remarkPathLinkify — Tauri 模式', () => {
  let originalTauri: boolean;
  // jsdom 注入的 Tauri native bridge 替身:Rust 端 convertFileSrc 的真实签名是
  // (filePath, protocol='asset') => string,我们 mock 后行为是返回固定 URL 模式。
  const tauriInternals = {
    metadata: { currentWindow: { label: 'main' } },
    convertFileSrc: (filePath: string, protocol = 'asset') =>
      `http://${protocol}.localhost/${encodeURI(filePath)}`,
  };

  beforeEach(() => {
    originalTauri = '__TAURI_INTERNALS__' in window;
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      value: tauriInternals,
      configurable: true,
      writable: true,
    });
  });

  afterEach(() => {
    if (!originalTauri) {
      // @ts-expect-error: 清理测试注入的全局
      delete window.__TAURI_INTERNALS__;
    }
  });

  it('图片后缀 → <img src="http://asset.localhost/...">(走 Tauri asset protocol)', async () => {
    const { remarkPathLinkify } = await import('../remarkPathLinkify');
    const { unified } = await import('unified');
    const remarkParse = (await import('remark-parse')).default;
    const remarkRehype = (await import('remark-rehype')).default;

    const tree = unified().use(remarkParse).use(remarkPathLinkify).parse('看 /Users/yxb/.nexus/outputs/koi.jpg');
    unified().use(remarkParse).use(remarkPathLinkify).runSync(tree);
    const hast = unified().use(remarkRehype).runSync(tree);
    const html = hastToHtml(hast as HastNode);

    // Tauri 2 asset URL 形如 http://asset.localhost/<encoded-path>
    // (Tauri 内部用 percent-encoding,但不同版本对路径的处理略有差异;
    // 这里只断言 URL 形如 asset protocol,且含绝对路径关键段)
    expect(html).toContain('src="http://asset.localhost/');
    expect(html).toContain('Users');
    expect(html).toContain('nexus');
    expect(html).toContain('outputs');
    expect(html).toContain('koi.jpg');
    // 不应出现 file://
    expect(html).not.toContain('file://');
  });

  it('非图片路径 → <a href="http://asset.localhost/..."> ', async () => {
    const { remarkPathLinkify } = await import('../remarkPathLinkify');
    const { unified } = await import('unified');
    const remarkParse = (await import('remark-parse')).default;
    const remarkRehype = (await import('remark-rehype')).default;

    const tree = unified().use(remarkParse).use(remarkPathLinkify).parse('日志在 /Users/yxb/.nexus/outputs/run.log');
    unified().use(remarkParse).use(remarkPathLinkify).runSync(tree);
    const hast = unified().use(remarkRehype).runSync(tree);
    const html = hastToHtml(hast as HastNode);

    expect(html).toContain('href="http://asset.localhost/');
    expect(html).toContain('Users');
    expect(html).toContain('run.log');
    expect(html).not.toContain('file://');
  });
});

// --- hast → HTML 简化版 helper(够用于断言) ---
interface HastNode {
  type: string;
  children?: HastNode[];
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
}

function hastToHtml(node: HastNode): string {
  if (node.type === 'text') return escapeHtml(node.value ?? '');
  if (node.type === 'element') {
    const props = node.properties ?? {};
    const attrs = Object.entries(props)
      .map(([k, v]) => ` ${k}="${escapeAttr(String(v))}"`)
      .join('');
    const inner = (node.children ?? []).map((c) => hastToHtml(c)).join('');
    return `<${node.tagName}${attrs}>${inner}</${node.tagName}>`;
  }
  if (node.type === 'root' && node.children) {
    return node.children.map((c) => hastToHtml(c)).join('');
  }
  return '';
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!));
}
function escapeAttr(s: string): string {
  return s.replace(/"/g, '&quot;');
}