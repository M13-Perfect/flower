import { defineConfig } from 'vitest/config'

// 独立于 vite.config（不挂 crx 插件）：只为提取器单测提供 jsdom 环境。
export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.ts'],
  },
})
