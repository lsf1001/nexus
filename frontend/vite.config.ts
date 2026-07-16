import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'node:path'

/**
 * base 策略:
 * - dev / 后端静态服务模式: base='/app/'(FastAPI 在 /app 挂 frontend)
 * - Tauri 模式(打包 + 桌面 webview): base='./' 相对路径
 *   Tauri 用 asset:// 协议 serve frontendDist,任何 /app/ 前缀都会 404
 *
 * 通过 VITE_TAURI 环境变量切换,Tauri build 时由 beforeBuildCommand 注入。
 *
 * resolve.alias: 把 `qrcode` 重定向到 `qrcode/lib/browser.js` —
 * qrcode 1.5.4 package.json 的 main 字段指向 ./lib/index.js,index.js
 * `module.exports = require('./server')`,server.js 又 require('dijkstrajs') /
 * pngjs / Node fs/path/stream。webview 里这些 require 失败 → toCanvas
 * 内部 throw → catch 静默 → canvas 空白(DMG 1.1.0/1.2.0 实测)。
 * ./lib/browser.js 是纯 CJS,只 require 自身 core+renderer,无 Node 内置。
 * 锁测试: src/components/__tests__/WechatPluginModal.test.ts
 */
const isTauriBuild = process.env.VITE_TAURI === 'true'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: isTauriBuild ? './' : '/app/',
  resolve: {
    alias: {
      qrcode: resolve(__dirname, 'node_modules/qrcode/lib/browser.js'),
    },
  },
  server: {
    port: 30077,
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:30000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
