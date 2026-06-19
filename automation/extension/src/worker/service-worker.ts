import { postOrder } from './client'

// MV3 service worker：接收内容脚本的发送请求，POST 到本地服务，回传结果。

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'FLOWER_SEND_ORDER') {
    postOrder(message.order, sender.tab?.url).then(sendResponse)
    return true // 异步响应：保持消息通道开启
  }
  return false
})
