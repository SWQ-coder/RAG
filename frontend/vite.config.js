import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

/**
 * Vite 开发服务器配置
 * 【开发思路】
 * 1. alias '@' → src：代码里 import '@/api' 就是 src/api，省去相对路径
 *    （router/views/stores 里大量用到）；
 * 2. server.proxy：前端跑在 3000 端口，后端 API 在 8000 端口。
 *    把 /api 开头的请求代理到后端——浏览器只看到同源 localhost:3000，
 *    规避跨域 CORS 问题（开发期不需要后端开 cors）；
 * 3. changeOrigin：代理时把 Host 头改成目标域名，后端收到的是
 *    localhost:8000 的 Host（避免后端因 Host 不符拒绝请求）。
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': resolve(__dirname, 'src') }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
