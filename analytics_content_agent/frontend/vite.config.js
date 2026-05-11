import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development, proxy API calls to the FastAPI backend.
// In production, nginx handles the proxy (see frontend/nginx.conf).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/upload-csv': { target: 'http://localhost:8000', changeOrigin: true },
      '/session':    { target: 'http://localhost:8000', changeOrigin: true },
      '/outputs':    { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
