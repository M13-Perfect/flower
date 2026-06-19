import { collectOrders, type OrderHit } from '../extractor/extractor'

// 内容脚本：在店小秘订单列表页，给每个订单行注入「→Flower」按钮（AI未识别的标红）。
// 单个订单抓取：点哪一单就提取并发送哪一单。vxe 会重渲染，用 MutationObserver 重注。
// 带控制台诊断：页面 F12 → Console 搜 "[Flower" 可确认脚本是否加载、识别到几单。

const BTN_CLASS = 'flower-send-btn'

function toast(message: string, ok = true): void {
  const el = document.createElement('div')
  el.textContent = message
  el.style.cssText =
    'position:fixed;right:16px;bottom:16px;z-index:2147483647;padding:10px 14px;border-radius:8px;' +
    `color:#fff;font-size:13px;max-width:320px;background:${ok ? '#1d9e75' : '#e24b4a'};box-shadow:0 2px 8px rgba(0,0,0,.2)`
  document.body.appendChild(el)
  setTimeout(() => el.remove(), 4000)
}

function sendOrder(hit: OrderHit, btn: HTMLButtonElement): void {
  const { order } = hit
  if (!order.order_id || !order.remark) {
    toast('未能识别订单号或定制信息', false)
    return
  }
  btn.disabled = true
  const original = btn.textContent
  btn.textContent = '发送中…'
  chrome.runtime.sendMessage({ type: 'FLOWER_SEND_ORDER', order }, (resp) => {
    btn.disabled = false
    if (chrome.runtime.lastError) {
      toast('发送失败：' + chrome.runtime.lastError.message, false)
      btn.textContent = original
      return
    }
    if (resp?.ok) {
      toast((resp.dedup ? '已更新：' : '已发送：') + order.order_id)
      btn.textContent = '✓ 已发送'
    } else {
      toast('发送失败：' + (resp?.error ?? '本地服务未启动？'), false)
      btn.textContent = original
    }
  })
}

function injectButtons(): number {
  const hits = collectOrders(document)
  for (const hit of hits) {
    const anchor = hit.anchorEl as HTMLElement
    if (anchor.querySelector('.' + BTN_CLASS)) continue
    const btn = document.createElement('button')
    btn.className = BTN_CLASS
    btn.type = 'button'
    btn.textContent = '→Flower'
    btn.title = hit.order.ai_unrecognized ? 'AI未识别订单，发送到 Flower' : '发送到 Flower'
    btn.style.cssText =
      'margin-left:6px;padding:2px 8px;border:none;border-radius:4px;font-size:12px;cursor:pointer;color:#fff;' +
      'vertical-align:middle;background:' + (hit.order.ai_unrecognized ? '#c0246f' : '#534ab7')
    btn.addEventListener('click', (event) => {
      event.preventDefault()
      event.stopPropagation()
      sendOrder(hit, btn)
    })
    anchor.appendChild(btn)
  }
  return hits.length
}

function start(): void {
  const found = injectButtons()
  // 诊断日志：在店小秘页面 F12 → Console 能看到这行，说明脚本已注入到本页。
  console.info('[Flower 取单助手] 已加载：', location.href, '｜本页识别订单', found, '个')
  if (document.body) {
    toast(
      found > 0
        ? `Flower 取单助手已就绪 · 本页 ${found} 单`
        : 'Flower 取单助手已加载，但本页未识别到订单（请在店小秘订单列表页，或等表格加载后刷新）',
      found > 0,
    )
  }
}

let scheduled = false
function scheduleInject(): void {
  if (scheduled) return
  scheduled = true
  setTimeout(() => {
    scheduled = false
    try {
      injectButtons()
    } catch {
      /* 重渲染瞬间的偶发错误忽略，下次 mutation 再注 */
    }
  }, 300)
}

start()
if (document.body) {
  new MutationObserver(scheduleInject).observe(document.body, { childList: true, subtree: true })
}
