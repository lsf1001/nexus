import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

/**
 * base 策略:
 * - dev / 后端静态服务模式: base='/app/'(FastAPI 在 /app 挂 frontend)
 * - Tauri 模式(打包 + 桌面 webview): base='./' 相对路径
 *   Tauri 用 asset:// 协议 serve frontendDist,任何 /app/ 前缀都会 404
 *
 * 通过 VITE_TAURI 环境变量切换,Tauri build 时由 beforeBuildCommand 注入。
 */
const isTauriBuild = process.env.VITE_TAURI === 'true'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: isTauriBuild ? './' : '/app/',
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
