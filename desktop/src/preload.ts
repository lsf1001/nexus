// Electron preload script —— 在 sandbox 模式下运行,负责把受控的 desktop API
// 暴露给 renderer。
//
// 关键:package.json 设置了 "type": "module",而 tsc 在 module=NodeNext 下
// 会输出 ESM 语法。但 Electron 默认按 CommonJS 加载 preload.js,会报
// "Cannot use import statement outside a module"。这里改用 require() 让
// 同一份 ts 既兼容 ESM 也兼容 CJS,简单稳定。
//
// electron-builder 把 dist/ 整目录打包进 app.asar,preload.js 路径
// app.getAppPath()/dist/src/preload.js 在 main.ts:28 显式指定。
// sandbox: true 时 preload 里只能用 require + contextBridge 的受限子集,
// 不能用 Node fs / path 等。这里只暴露 platform / appKind,沙箱安全。

const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("nexusDesktop", {
  platform: "macos",
  appKind: "desktop"
});