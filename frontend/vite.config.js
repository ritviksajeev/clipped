import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend serves the built files from clipped/web.
// During development, `npm run dev` proxies API calls to a running `clipped serve`.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../clipped/web', emptyOutDir: true, chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/media': backend,
      '/oauth2callback': backend,
    },
  },
})
