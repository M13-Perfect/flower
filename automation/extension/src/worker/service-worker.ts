import { runAutoCycle } from './auto_cycle'
import {
  getMarkPending,
  getRefundPending,
  getRescrapeQueue,
  getScrapeControl,
  grabOrderIfNeeded,
  postMarkResult,
  postOrder,
  postOrdersBatch,
  postRecheck,
  postRescrapeResult,
  postScrapeDiff,
  reconcileAiStatus,
} from './client'

// MV3 service worker：内容脚本只读 DOM，HTTP 全经此处（内容脚本 fetch 受店小秘源 CORS 限制）。
// 两类消息：手动「→Flower」单发；自动循环一轮（内容脚本抓本页订单 → 这里 diff + 逐单推送）。

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'FLOWER_SEND_ORDER') {
    postOrder(message.order, sender.tab?.url).then(sendResponse)
    return true // 异步响应：保持消息通道开启
  }
  // 手动「→Flower」按钮（标准1 门控上传）：AI已处理跳过、否则查库 diff 决定是否上传。
  if (message?.type === 'FLOWER_GRAB_ORDER') {
    grabOrderIfNeeded(message.order, sender.tab?.url)
      .then(sendResponse)
      .catch((error) => sendResponse({ uploaded: false, error: String(error) }))
    return true
  }
  if (message?.type === 'FLOWER_AUTO_CYCLE') {
    runAutoCycle(message.orders ?? [], {
      getControl: getScrapeControl,
      postDiff: postScrapeDiff,
      pushOrders: (orders) => postOrdersBatch(orders, sender.tab?.url),
      getPending: getRefundPending,
      postRecheck,
    })
      .then(sendResponse)
      .catch((error) => sendResponse({ enabled: false, intervalSeconds: 60, error: String(error) }))
    return true
  }
  // 定向重抓（option B）：内容脚本做店小秘搜索（DOM），HTTP 经此处。
  if (message?.type === 'FLOWER_RESCRAPE_PULL') {
    getRescrapeQueue()
      .then((ids) => sendResponse({ ids }))
      .catch(() => sendResponse({ ids: [] }))
    return true
  }
  if (message?.type === 'FLOWER_RESCRAPE_RESULT') {
    postRescrapeResult(message.orderId, Boolean(message.found), message.refundStatus)
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }))
    return true
  }
  // 读任务租约（authorized + 时间范围 + task_id）：内容脚本据此 fail-closed + 过滤订单。
  // 服务不可达/出错 → 兜底为「未授权」（绝不因网络抖动误判已授权）。
  if (message?.type === 'FLOWER_GET_CONTROL') {
    getScrapeControl()
      .then((c) => sendResponse(c))
      .catch(() =>
        sendResponse({
          authorized: false,
          enabled: false,
          interval_seconds: 60,
          scrape_from: null,
          scrape_to: null,
          task_id: null,
          allowed_actions: null,
        }),
      )
    return true
  }
  if (message?.type === 'FLOWER_MARK_PULL') {
    getMarkPending(message.limit)
      .then((jobs) => sendResponse({ jobs }))
      .catch(() => sendResponse({ jobs: [] }))
    return true
  }
  if (message?.type === 'FLOWER_MARK_RESULT') {
    postMarkResult(message.orderId, message.action, Boolean(message.ok), message.detail)
      .then(() => sendResponse({ ok: true }))
      .catch(() => sendResponse({ ok: false }))
    return true
  }
  // AI 识别状态对账：内容脚本读到订单行 → 上报页面标记现状 → 服务回 desired_tag。
  // 查库失败 → reconcileAiStatus 返回 null（内容脚本据此跳过、不改标签）。
  if (message?.type === 'FLOWER_AI_RECONCILE') {
    reconcileAiStatus(message.orderId, Boolean(message.aiDone), Boolean(message.aiUnrecognized))
      .then((decision) => sendResponse(decision))
      .catch(() => sendResponse(null))
    return true
  }
  return false
})
