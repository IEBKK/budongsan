import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages 는 /{repo}/ 하위에 배포되므로 base 를 주입받는다.
// Cloudflare Pages 로 옮기면 VITE_BASE 없이 '/' 가 된다.
export default defineConfig({
  base: process.env.VITE_BASE || '/',
  plugins: [react()],
  build: { outDir: 'dist', assetsDir: 'assets', sourcemap: false },
})
