/**
 * vitest 配置 — 与 vite.config.ts 共享 plugin(react/tailwind),环境换 jsdom。
 *
 * 测试范围:纯函数 + hook 派发器(useWsMessageRouter / useChatSend),
 * 走 React Testing Library render + jsdom DOM,不依赖真实 WS / 真后端。
 *
 * 注意:`vite.config.ts` 已在用,Tauri build 时 base='/app/' 重写(frontend
 * 静态服务),我们这里不再写 base/test 字段覆盖 — 通过 defineConfig merge
 * 走 vitest 默认(无 base 影响 jsdom 路径解析)。
 */
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
