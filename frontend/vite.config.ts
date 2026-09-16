import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Imported from vitest/config rather than vite so this `test` block is typed
  // without a triple-slash reference.
  test: {
    // Component tests need DOM APIs; the default node environment has none.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
