import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'
import pkg from './package.json'

export default defineConfig({
  plugins: [vue(), tailwindcss()],
  // Version shown in the sidebar footer. Single source: package.json "version",
  // bumped manually when tagging a release.
  define: { __APP_VERSION__: JSON.stringify(`v${pkg.version}`) },
  server: {
    // Dev: proxy API calls to the FastAPI backend so the browser sees one origin.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
