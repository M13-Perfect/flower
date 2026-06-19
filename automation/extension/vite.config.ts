import { defineConfig } from 'vite'
import { crx } from '@crxjs/vite-plugin'
import manifest from './manifest.config'

// @crxjs 负责把 manifest 里指向的 .ts 源（content / service worker / popup）打包成
// MV3 可加载的产物并改写 manifest 路径，省去手搓 rollup 多入口/格式的麻烦。
export default defineConfig({
  plugins: [crx({ manifest })],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
