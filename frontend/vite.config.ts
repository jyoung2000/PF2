import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:5643', ws: true },
      '/media': { target: 'http://localhost:5643' },
    },
  },
  build: { chunkSizeWarningLimit: 900 },
})
