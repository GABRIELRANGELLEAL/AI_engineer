import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const backendUrl = process.env.BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    proxy: {
      '/validate-keys': backendUrl,
      '/documents': backendUrl,
      '/question': backendUrl,
      '/stats': backendUrl,
      '/health': backendUrl,
    },
  },
})
