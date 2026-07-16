/**
 * WechatPluginModal QR 渲染契约锁测试(2026-07-16)。
 *
 * WHY:DMG 1.1.0 (2026-07-15 build) 装到 /Applications 后,点击"绑定微信"
 * → modal 弹出 → 点"绑定微信"调 /api/channels/wechat/qr → 200 OK
 * → canvas 还是空白。原因:`import('qrcode')` 被 vite code-split 成
 * browser-xxx.js chunk,运行时 webview 加载该 chunk 路径解析失败
 * (`asset://` 协议下动态 import 相对路径不稳定),`mod.toCanvas` 永远
 * undefined,canvas 静默不渲染。
 *
 * 锁定两条契约:
 *   1. WechatPluginModal 源码**不**包含动态 `import('qrcode')` —
 *      必须静态 import,qrcode 库打主 bundle,避免运行时 dynamic chunk 加载。
 *   2. WechatPluginModal 源码**包含** `import ... from 'qrcode'` —
 *      静态 import 必须存在(toCanvas 必须能拿到)。
 *
 * 实现形式:读源文件当字符串断言。源码契约不被 vitest 行为覆盖,
 * 即使 jsdom 跑得动,字符串 grep 也跑得动。
 */
import { describe, expect, it } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const SOURCE = resolve(HERE, "../WechatPluginModal.tsx");
const VITE_CONFIG = resolve(HERE, "../../../vite.config.ts");
const source = readFileSync(SOURCE, "utf8");
const viteConfig = readFileSync(VITE_CONFIG, "utf8");

describe("WechatPluginModal QR 渲染契约(qrcode 必须静态 import,避免 DMG webview dynamic chunk 加载失败)", () => {
  it("源码**不**包含动态 import('qrcode')(asset:// 下 dynamic chunk 路径不稳定 → canvas 空白)", () => {
    // 任何形式的动态 import,包括反引号模板字符串(grep 兜底)
    const dynamicImportPatterns = [
      /import\s*\(\s*['"`]qrcode['"`]\s*\)/,
      /import\s*\(\s*`[^`]*qrcode[^`]*`\s*\)/,
      /import\s*\(\s*qrcode\s*\)/,
    ];
    for (const re of dynamicImportPatterns) {
      expect(source).not.toMatch(re);
    }
  });

  it("源码**包含**静态 import qrcode(toCanvas 必须能拿到)", () => {
    // 静态 import 必须以 from 'qrcode' / from "qrcode" 形式出现
    const staticImportPatterns = [
      /import\s+[\w*{},\s]+\s+from\s+['"]qrcode['"]/,
      /import\s+['"]qrcode['"]/,
    ];
    const hasStatic = staticImportPatterns.some((re) => re.test(source));
    expect(hasStatic).toBe(true);
  });

  it("useEffect 里的 QR 绘制**同步**走 QRCode.toCanvas(不打 then 链)", () => {
    // 静态 import 后 QRCode.toCanvas 直接可用,不通过 .then 链 wait chunk
    // 第一个 useEffect 块:`if (qrData?.qrcode_url && canvasRef.current)`
    const start = source.indexOf("if (qrData?.qrcode_url && canvasRef.current)");
    expect(start).toBeGreaterThan(-1);
    const block = source.slice(start, start + 400);
    expect(block).toMatch(/QRCode\.toCanvas|toCanvas\s*\(/i);
    // 反向:不允许 import 表达式遗留
    expect(block).not.toMatch(/import\s*\(/);
  });

  it("vite.config 必须 alias qrcode → qrcode/lib/browser.js(绕开 server 入口拉 dijkstrajs/pngjs/Node 内置)", () => {
    // WHY:qrcode 1.5.4 package.json 的 main 字段指向 ./lib/index.js,
    //     index.js 一上来 `module.exports = require('./server')`,server.js
    //     require('dijkstrajs') + pngjs + Node fs/path/stream。
    //     webview 里 require 失败 → toCanvas 内部 throw → catch 静默 → canvas 空白。
    //     必须显式 alias 到 ./lib/browser.js(纯 CJS,只 require 自身 core+renderer)。
    const aliasBlock = viteConfig.match(/resolve:\s*\{[\s\S]*?\}/);
    expect(aliasBlock, "vite.config 必须有 resolve.alias 块").not.toBeNull();
    const block = aliasBlock![0];
    expect(block, "alias 必须包含 qrcode → qrcode/lib/browser.js").toMatch(
      /qrcode\s*:\s*resolve\(__dirname,\s*['"]node_modules\/qrcode\/lib\/browser\.js['"]\)/,
    );
  });

  it("qrcode/lib/browser.js 必须存在且是干净浏览器版(不 require dijkstrajs/pngjs)", () => {
    // 物理文件检查 — 万一 npm 升级 qrcode 包结构变了立刻报警
    const browserPath = resolve(HERE, "../../../node_modules/qrcode/lib/browser.js");
    expect(existsSync(browserPath), `缺失: ${browserPath}`).toBe(true);
    const browserSrc = readFileSync(browserPath, "utf8");
    expect(browserSrc).not.toMatch(/require\(['"]dijkstrajs['"]\)/);
    expect(browserSrc).not.toMatch(/require\(['"]pngjs['"]\)/);
    expect(browserSrc).not.toMatch(/require\(['"]fs['"]\)/);
    expect(browserSrc).not.toMatch(/require\(['"]path['"]\)/);
  });
});