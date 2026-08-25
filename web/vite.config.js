import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Relative base so `npm run build` produces a dist/ you can open from disk
  // or drop on any static host without rewriting asset paths.
  base: './',
  server: { open: true },
})
