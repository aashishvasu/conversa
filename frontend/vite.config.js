import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  server: {
    // Dev: proxy API calls to the FastAPI backend so the browser sees one origin.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
