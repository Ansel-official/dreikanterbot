import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 本地开发：Vite 直接代理到本机后端，WebSocket 同样走 /ws。
// 生产：前端静态文件由 Nginx 托管，同源 /api 与 /ws 由 Nginx 反代。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    watch: {
      // 某些编辑器/代理会在源码旁创建临时目录，Windows 上被锁住会让 chokidar 崩溃
      ignored: ['**/*.tmpdir/**', '**/.*.tmpdir/**', '**/.package.json.*'],
    },
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
})
