import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  build: {
    outDir: 'dist-mock',
    rollupOptions: {
      input: { mock: 'mock.html' },
    },
  },
  server: { port: 5199, host: '127.0.0.1' },
})
