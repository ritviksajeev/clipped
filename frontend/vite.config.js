import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The FastAPI backend serves the built files from clippilot/web.
// During development, `npm run dev` proxies API calls to a running `clippilot serve`.
const backend = 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../clippilot/web', emptyOutDir: true, chunkSizeWarningLimit: 800 },
  server: {
    port: 5173,
    proxy: {
      '/api': backend,
      '/media': backend,
      '/oauth2callback': backend,
    },
  },
})
