import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/app/',
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
