import { defineManifest } from '@crxjs/vite-plugin'

export default defineManifest({
  manifest_version: 3,
  name: 'Flower 取单助手',
  version: '0.1.0',
  description: '在店小秘订单详情页一键把订单发送到本地 Flower 取单服务（automation 一期）。',
  action: {
    default_popup: 'src/popup/popup.html',
    default_title: 'Flower 取单助手',
  },
  background: {
    service_worker: 'src/worker/service-worker.ts',
    type: 'module',
  },
  content_scripts: [
    {
      matches: ['https://*.dianxiaomi.com/*', 'https://dianxiaomi.com/*'],
      js: ['src/content/content.ts'],
      run_at: 'document_idle',
      all_frames: true,
    },
  ],
  // service worker fetch 到本地服务需要 host 权限。
  host_permissions: ['http://127.0.0.1:8770/*', 'http://localhost:8770/*'],
})
