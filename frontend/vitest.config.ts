import { defineConfig, mergeConfig } from 'vitest/config'
import viteConfig from './vite.config.ts'

// Testy zachowania UI (#58): React renderowany w jsdom, backend zastąpiony mockiem fetch.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: 'jsdom',
      include: ['tests/**/*.test.tsx'],
    },
  }),
)
