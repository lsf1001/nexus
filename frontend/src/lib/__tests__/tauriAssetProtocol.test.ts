/**
 * tauri.conf.json 配置守门测试 — 2026-07-14 修复 chat 消息 file:// 图片渲染时建立。
 *
 * 背景:pathLinkify 把聊天里的 `/Users/.../koi.jpg` 转成 <img src=...>,但 Tauri webview
 * 的 CSP `img-src 'self' data: blob:` 会拒绝 file:// — 缩略图破图占位。
 *
 * 修法:开启 `app.security.assetProtocol` + 在 CSP `img-src` 加 `asset: http://asset.localhost`,
 * 这样前端 `convertFileSrc(path)` 产出的 `http://asset.localhost/<encoded>` 就能被 webview
 * 直接 fetch,真渲染缩略图。
 *
 * 测试断言(防止后续无意改回去):
 *  1. assetProtocol.enable === true
 *  2. assetProtocol.scope 至少含 `$HOME/.nexus/**`(LLM shell_run 输出目录)
 *  3. CSP img-src 同时含 'asset:' 和 'http://asset.localhost'(Tauri 2 v2.0+ 协议名)
 *  4. CSP img-src 仍然含 'self'(保留 React 静态资源)
 *
 * 为什么这里测 config 而不是端到端:配置是"决策点",改坏了真 DMG 才会暴露;
 * 端到端测试 DMG 重打 7 分钟,日常回归不值。配置守门在 ms 级。
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

interface TauriConfig {
  app: {
    security: {
      csp: string;
      assetProtocol: {
        enable: boolean;
        scope: string[] | { allow: string[]; deny?: string[]; requireLiteralLeadingDot?: boolean };
      };
    };
  };
}

function loadConfig(): TauriConfig {
  // vitest 在 frontend/ 下运行,test 文件在 src/lib/__tests__/foo.test.ts
  // → /Users/yxb/projects/nexus/frontend/ (3 个 ..)
  // → 再 ../desktop/src-tauri/tauri.conf.json
  const here = fileURLToPath(import.meta.url);
  const path = resolve(here, '..', '..', '..', '..', '..', 'desktop', 'src-tauri', 'tauri.conf.json');
  return JSON.parse(readFileSync(path, 'utf-8')) as TauriConfig;
}

function normalizeScope(scope: TauriConfig['app']['security']['assetProtocol']['scope']): string[] {
  return Array.isArray(scope) ? scope : scope.allow;
}

describe('desktop/src-tauri/tauri.conf.json — assetProtocol + CSP', () => {
  it('assetProtocol.enable === true(否则 convertFileSrc 仍会被 webview 拒绝)', () => {
    const cfg = loadConfig();
    expect(cfg.app.security.assetProtocol.enable).toBe(true);
  });

  it('assetProtocol.scope 至少含 $HOME/.nexus/**(LLM shell_run 默认输出目录)', () => {
    const cfg = loadConfig();
    const scope = normalizeScope(cfg.app.security.assetProtocol.scope);
    expect(scope).toContain('$HOME/.nexus/**');
  });

  it('CSP img-src 含 asset: 协议名 + http://asset.localhost(Tauri 2 asset URL 形如 http://asset.localhost/<encoded>)', () => {
    const cfg = loadConfig();
    const csp = cfg.app.security.csp;
    // 抽出 img-src '...' 这一段
    const imgSrc = csp.match(/img-src\s+([^;]+)/)?.[1] ?? '';
    expect(imgSrc).toContain("'self'");
    expect(imgSrc).toContain('asset:');
    expect(imgSrc).toContain('http://asset.localhost');
  });
});