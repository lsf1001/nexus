import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/app/',
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:30000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
})
