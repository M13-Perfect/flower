import { checkHealth } from '../worker/client'

async function render(): Promise<void> {
  const el = document.getElementById('health')
  if (!el) return
  const ok = await checkHealth()
  el.innerHTML = ok
    ? '<span class="dot ok"></span>本地服务在线 (127.0.0.1:8770)'
    : '<span class="dot bad"></span>本地服务未启动（先运行 inbox-service）'
}

void render()
