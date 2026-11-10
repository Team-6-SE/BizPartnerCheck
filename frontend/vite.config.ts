/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
    server: {
    // During development, API calls go to the FastAPI backend on port 8000.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    // Unit tests next to the code (*.test.ts). The Playwright tests in e2e/ run separately.
    include: ['src/**/*.test.{ts,tsx}'],
  },
})