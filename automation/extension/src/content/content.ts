import {
  clickMarkItem,
  clickMarkTrigger,
  getMarkPopover,
  type MarkLabelKey,
  markCancelButton,
  markConfirmButton,
  readOrderRowMarks,
  readPopoverSelection,
} from '../extractor/dianxiaomi_mark'
import { canSearch, fillSearchAndSubmit, findOrderInResults } from '../extractor/dianxiaomi_search'
import { collectOrders, type OrderHit } from '../extractor/extractor'
import type { MarkJobInput } from '../worker/mark_writeback'
import { runMarkJobs } from '../worker/mark_writeback'
import {
  handleManualFlowerOrder,
  type ManualMarkDeps,
  type ManualOutcome,
  manualMarkQueue,
} from '../worker/manual_mark'
import { runReconcile } from '../worker/ai_reconcile'
import { isAuthorized, pageBelowWindowFloor } from '../worker/authorization'
import type { DatabaseResult, RawOrder, ReconcileDecision, ScrapeControl } from '../shared/contract'
import {
  clickNextPage,
  clickPrevPage,
  isPrevDisabled,
  scrollTableToBottom,
} from '../extractor/dianxiaomi_pager'
import { runPagedSweep } from '../worker/paginate'
import { runRescrapeJobs } from '../worker/rescrape'

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

// 每单 in-flight 锁（§八.4）：防连点 / 防同一单并发上传+打标。
const manualInFlight = new Set<string>()

/** 把决策结果映射成 toast + 按钮态 + 控制台诊断（F12 搜 "[Flower 手动]" 看每单 reasonCode）。 */
function applyManualOutcome(
  btn: HTMLButtonElement,
  original: string | null,
  outcome: ManualOutcome,
  orderId: string,
): void {
  console.info('[Flower 手动]', orderId, outcome.action, outcome.reasonCode)
  switch (outcome.reasonCode) {
    case 'INVALID_ORDER_NO':
      toast('未能识别订单号', false)
      btn.textContent = original
      break
    case 'DUPLICATE_AI_LABEL_CONFLICT':
      toast(`⚠ ${orderId} 同时有「AI未识别」「AI已处理」标签冲突，已跳过`, false)
      btn.textContent = '⚠ 标签冲突'
      break
    case 'SKIP_ALREADY_AI_DONE':
      toast('该单已标记 AI已处理，跳过')
      btn.textContent = '✓ 已处理'
      break
    case 'NO_LABEL_UPLOAD_FAILED':
      toast('上传失败，未打标', false)
      btn.textContent = original
      break
    case 'NO_CHANGE_ALREADY_AI_UNRECOGNIZED':
      toast('已上传（该单已是 AI未识别，标签不变）')
      btn.textContent = '✓ 已上传'
      break
    case 'ADD_AI_UNRECOGNIZED_FOR_NEW_ORDER':
      toast('已上传并打「AI未识别」：' + orderId)
      btn.textContent = '✓ 已打标'
      break
    case 'LABEL_VERIFICATION_FAILED':
      toast('已上传，但打标校验未通过（可重试或手动检查）', false)
      btn.textContent = '⚠ 打标失败'
      break
    case 'NO_LABEL_EXISTING_DATABASE_ORDER':
      toast('已上传（库中已存在，标签不变）')
      btn.textContent = '✓ 已上传'
      break
    case 'NO_LABEL_DATABASE_RESULT_UNKNOWN':
      toast('已上传（数据库状态未知，未打标）', false)
      btn.textContent = '✓ 已上传'
      break
    default:
      btn.textContent = original
  }
}

function sendOrder(hit: OrderHit, btn: HTMLButtonElement): void {
  const { order } = hit
  // remark 可选（D-1）：只要有订单号且「有备注或有行项目」即可发；标品/无定制单靠 items[] 承载。
  if (!order.order_id || (!order.remark && !order.items?.length)) {
    toast('未能识别订单号或定制信息', false)
    return
  }
  // 每单 in-flight 锁（§八.4）：连点 / 重复触发 → 直接忽略，同一单只处理一次。
  if (manualInFlight.has(order.order_id)) {
    toast('该单正在处理中…')
    return
  }
  manualInFlight.add(order.order_id)
  btn.disabled = true
  const original = btn.textContent
  btn.textContent = '处理中…'

  // 手动单笔**条件打标**（决策表见 manual_mark.handleManualFlowerOrder）：
  //   上传经 SW（内容脚本 fetch 受店小秘源 CORS 限制）→ 据数据库三态判是否打标 → CREATED_NEW 才 force 打「AI未识别」。
  const deps: ManualMarkDeps = {
    upload: async () => {
      const resp = await askSW<{ uploaded?: boolean; databaseResult?: DatabaseResult; error?: string }>({
        type: 'FLOWER_GRAB_ORDER',
        order,
      })
      // SW 失联（askSW 返回 undefined）→ 视为上传失败（不误判新建、不打标）。
      if (!resp) return { success: false, error: 'SW 无响应' }
      return { success: Boolean(resp.uploaded), databaseResult: resp.databaseResult, error: resp.error }
    },
    addAiUnrecognizedAndVerify: (orderId) => runManualMarkOnce(orderId),
  }

  handleManualFlowerOrder(order, deps)
    .then((outcome) => applyManualOutcome(btn, original, outcome, order.order_id))
    .catch((error) => {
      toast('处理失败：' + String((error as Error)?.message ?? error), false)
      btn.textContent = original
    })
    .finally(() => {
      btn.disabled = false
      manualInFlight.delete(order.order_id)
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
    const done = hit.order.ai_done
    btn.title = done
      ? '已标记 AI已处理（点击跳过上传）'
      : hit.order.ai_unrecognized
        ? 'AI未识别订单，发送到 Flower'
        : '发送到 Flower'
    btn.style.cssText =
      'margin-left:6px;padding:2px 8px;border:none;border-radius:4px;font-size:12px;cursor:pointer;color:#fff;' +
      'vertical-align:middle;background:' + (done ? '#1d9e75' : hit.order.ai_unrecognized ? '#c0246f' : '#534ab7')
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

// ── 自动抓取循环（定时器在内容脚本里自重排；抓 DOM 后交 SW 做 diff+推送）──
// 关闭/出错时按默认间隔回探（这样 flower 后续打开开关能被下一轮拾起）；页面刷新→content 重注→循环自动重启。
const DEFAULT_POLL_SECONDS = 60
let autoTimer: ReturnType<typeof setTimeout> | undefined

function scheduleAutoCycle(delaySeconds: number): void {
  if (autoTimer !== undefined) clearTimeout(autoTimer)
  autoTimer = setTimeout(runAutoCycleOnce, Math.max(5, delaySeconds) * 1000)
}

// 自动翻页 + 游标（「页面记录」，避免每轮从第 1 页重读所有页、压系统）。游标存 chrome.storage.local。
// ⚠️ 真机校准点：翻页/滚动后 vxe AJAX+重渲染的等待时长、虚拟滚动是否真把本页 100 行都渲出、回第 1 页方式。
//   先给保守默认，真机按需调这三个常数。
const CURSOR_KEY = 'flower_scrape_cursor'
const TASK_KEY = 'flower_scrape_task' // 上次见过的任务 id；变更即清游标（不恢复历史扫描，验收 #8/#10）
const PAGE_SETTLE_MS = 1200 // 翻页后等 vxe AJAX + 行重渲染
const SCROLL_SETTLE_MS = 400 // 滚到底后等虚拟滚动补渲染
const MAX_SWEEP_PAGES = 30 // 一轮最多翻几页（防超大 backlog 扫爆 / 选择器击穿死循环）
const sleep = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
let sweepRunning = false

async function getScrapeCursor(): Promise<string | null> {
  try {
    const r = await chrome.storage.local.get(CURSOR_KEY)
    const v = r?.[CURSOR_KEY]
    return typeof v === 'string' ? v : null
  } catch {
    return null // storage 不可用 → 游标失效，退化为翻到末页/上限，仍正确（diff 兜底）
  }
}
async function setScrapeCursor(cursor: string): Promise<void> {
  try {
    await chrome.storage.local.set({ [CURSOR_KEY]: cursor })
  } catch {
    /* 同上，写不成不致命 */
  }
}

/**
 * P0：任务变更（含从「无任务」到「有任务」、或换了新任务）时清掉旧翻页游标。
 * 防止扩展/浏览器重启后用旧游标恢复一次历史方向的扫描（验收 #8/#10：旧游标不能绕过当前授权）。
 * chrome.storage 里残留的游标**不是授权来源**——授权只认服务端 authorized；这里只是不让它影响翻页范围。
 */
async function resetCursorIfTaskChanged(taskId: string | null | undefined): Promise<void> {
  try {
    const r = await chrome.storage.local.get(TASK_KEY)
    const prev = typeof r?.[TASK_KEY] === 'string' ? r[TASK_KEY] : null
    if (prev !== (taskId ?? null)) {
      await chrome.storage.local.remove(CURSOR_KEY)
      await chrome.storage.local.set({ [TASK_KEY]: taskId ?? '' })
    }
  } catch {
    /* storage 不可用：游标失效会退化为按时间窗过滤 + 末页/上限，仍正确 */
  }
}

/** 回到第 1 页：连点「上一页」到禁用（稳态本就在首页 → 0 次点击）。有上限防卡死。 */
async function pagerGotoFirst(): Promise<void> {
  for (let i = 0; i < MAX_SWEEP_PAGES; i++) {
    if (isPrevDisabled(document)) return
    if (!clickPrevPage(document)) return
    await sleep(PAGE_SETTLE_MS)
  }
}

/** 滚到底加载满本页（vxe 虚拟滚动）→ 读本页订单。 */
async function readCurrentPage(): Promise<RawOrder[]> {
  scrollTableToBottom(document)
  await sleep(SCROLL_SETTLE_MS)
  return collectOrders(document).map((hit) => hit.order)
}

async function runAutoCycleOnce(): Promise<void> {
  if (sweepRunning) return // 上一轮翻页还没结束 → 跳过本次触发（翻页耗时可能超过一个间隔）
  // 廉价 gate：不在订单列表页就不动 DOM。
  let onList: boolean
  try {
    onList = collectOrders(document).length > 0
  } catch {
    scheduleAutoCycle(DEFAULT_POLL_SECONDS) // vxe 重渲染瞬间偶发，下轮再来
    return
  }
  if (!onList) {
    scheduleAutoCycle(DEFAULT_POLL_SECONDS) // 当前不在订单列表页
    return
  }
  // ⚠️ P0：唯一执行判据 = 服务端任务租约授权（authorized）。未授权 → **绝不翻页/滚动/抓取/打标**，
  // 只按间隔回探（等 flower 下发任务后被下一轮拾起）。不信任何本地缓存的 enabled/running/旧游标。
  const control = await askSW<ScrapeControl>({ type: 'FLOWER_GET_CONTROL' })
  const intervalSeconds = control?.interval_seconds || DEFAULT_POLL_SECONDS
  if (!isAuthorized(control)) {
    scheduleAutoCycle(intervalSeconds)
    return
  }
  // 任务变更 → 清旧游标（不恢复历史方向扫描）。
  await resetCursorIfTaskChanged(control?.task_id)
  sweepRunning = true
  let pushed = 0
  let failed = 0
  let blocked = 0
  try {
    const sweep = await runPagedSweep({
      gotoFirstPage: pagerGotoFirst,
      readPage: readCurrentPage,
      runCycle: async (orders) => {
        if (orders.length === 0) return
        const resp = await askSW<{ pushed?: number; failed?: number; recheckBlocked?: number }>({
          type: 'FLOWER_AUTO_CYCLE',
          orders,
        })
        if (resp) {
          pushed += resp.pushed ?? 0
          failed += resp.failed ?? 0
          blocked += resp.recheckBlocked ?? 0
        }
      },
      gotoNextPage: async () => {
        if (!clickNextPage(document)) return false
        await sleep(PAGE_SETTLE_MS)
        return true
      },
      getCursor: getScrapeCursor,
      setCursor: setScrapeCursor,
      maxPages: MAX_SWEEP_PAGES,
      // P0：整页越过任务时间窗下界 → 停止翻页（不回溯扫描历史订单，验收 #4/#7）。
      reachedFloor: (orders) => pageBelowWindowFloor(orders, control),
    })
    if (pushed || failed) {
      toast(
        `自动抓取：推送 ${pushed} 单` + (failed ? `（失败 ${failed}）` : '') + ` · 翻 ${sweep.pages} 页`,
        !failed,
      )
    }
    // 退款重抓闭环：发现在产单退款/取消 → 红色告警（操作员据此停止该单生产）。
    if (blocked) {
      toast(`⚠ 退款拦截：检测到 ${blocked} 个在产单已退款/取消`, false)
    }
  } catch {
    /* 本轮失败忽略，下轮再来 */
  } finally {
    sweepRunning = false
    scheduleAutoCycle(intervalSeconds)
    // 抓完**立刻**给店小秘打标（不等后台 8s 循环；用户要求保留）：上传成功的单服务端已入队 mark_unrecognized。
    runMarkOnce()
  }
}

// ── 定向重抓轮询（option B）：在店小秘「搜索订单」页时，定期拉「该重抓」队列 → 逐单搜索+抓取+回填 ──
// 不在搜索页 → runRescrapeJobs 直接 skipped（不发 HTTP、不动队列），等操作员切到搜索页再处理。
// 轮询间隔 1s：配合 Ezcad recheck_fresh 15s 超时预算（入队→拉取≤1s + 搜索≤6s + 回填往返≈1s）。
// 这组常数是三仓冻结契约，改前看 Ezcad inbox_client._NOT_READY_HINT 附近注释。
const RESCRAPE_POLL_SECONDS = 1
let rescrapeTimer: ReturnType<typeof setTimeout> | undefined
let rescrapeNotReadyWarned = false

function askSW<T = unknown>(message: unknown): Promise<T | undefined> {
  return new Promise((resolve) => {
    try {
      chrome.runtime.sendMessage(message, (resp) => {
        resolve(chrome.runtime.lastError ? undefined : (resp as T))
      })
    } catch {
      resolve(undefined)
    }
  })
}

const rescrapeDelay = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))

async function searchAndExtract(orderId: string): Promise<RawOrder | null> {
  // 先看当前页是否已可见该单（操作员常待在「已退款/全部订单」等列表页）——可见就直接读，不必驱动搜索。
  const onPage = findOrderInResults(document, orderId)
  if (onPage) return onPage
  // 不可见 → 用搜索框（搜索订单页）按单号搜出来。
  if (!fillSearchAndSubmit(document, orderId)) return null
  const deadline = Date.now() + 6000 // 等店小秘 AJAX 结果渲染，最多 6s
  while (Date.now() < deadline) {
    await rescrapeDelay(400)
    const order = findOrderInResults(document, orderId)
    if (order) return order
  }
  return findOrderInResults(document, orderId)
}

function scheduleRescrape(seconds: number): void {
  if (rescrapeTimer !== undefined) clearTimeout(rescrapeTimer)
  rescrapeTimer = setTimeout(runRescrapeOnce, Math.max(1, seconds) * 1000)
}

function runRescrapeOnce(): void {
  runRescrapeJobs({
    canSearch: () => canSearch(document),
    getQueue: async () => (await askSW<{ ids: string[] }>({ type: 'FLOWER_RESCRAPE_PULL' }))?.ids ?? [],
    searchAndExtract,
    pushOrder: async (order) => {
      const resp = await askSW<{ ok?: boolean }>({ type: 'FLOWER_SEND_ORDER', order })
      return { ok: Boolean(resp?.ok) }
    },
    postResult: async (orderId, found, refundStatus) => {
      await askSW({ type: 'FLOWER_RESCRAPE_RESULT', orderId, found, refundStatus })
    },
  })
    .then((r) => {
      if (r.found) {
        toast(`定向重抓：已为 ${r.found} 个订单重抓店小秘退款状态`)
        rescrapeNotReadyWarned = false
      }
      // 不在搜索页时一次性提示（F12 可秒判：是没开搜索页还是选择器被改版击穿）。
      if (r.skipped && !rescrapeNotReadyWarned) {
        rescrapeNotReadyWarned = true
        console.warn(
          '[Flower 定向重抓] 当前页不是店小秘「搜索订单」页（找不到 #orderSearchInput）。' +
            'Ezcad 的退款核对会因拿不到实时状态而超时阻断。请打开店小秘「搜索订单」页并保持登录。当前 URL：' +
            location.href,
        )
      } else if (!r.skipped) {
        rescrapeNotReadyWarned = false
      }
    })
    .catch(() => undefined)
    .finally(() => scheduleRescrape(RESCRAPE_POLL_SECONDS))
}

// ── 标记回写轮询：给店小秘订单打 AI未识别/AI已处理（模拟网页操作）──
// 写操作有店小秘封号风险 → 间隔较慢、串行、每步带延时；仅在 flower 开启自动抓(/scrape/control enabled)时跑。
const MARK_POLL_SECONDS = 8
const MARK_DISABLED_BACKOFF_SECONDS = 30
const MARK_BATCH_LIMIT = 3 // 每轮最多打标几单（串行写有封号风险，剩余留下轮；契约「每轮只处理少量」）
const RECONCILE_QUERY_LIMIT = 25 // AI 对账每轮最多查询几单（查询便宜但限频防压服务/SW；剩余留下轮）
let markTimer: ReturnType<typeof setTimeout> | undefined

const markDelay = (ms: number): Promise<void> => new Promise((r) => setTimeout(r, ms))
let markBusy = false // 防止「抓取触发」与「定时器触发」并发打标，抢同一个单例弹窗

/**
 * 构造店小秘标记弹窗操作的一组闭包（自动打标轮询 + 手动 force 打标共用，避免重复 DOM 时序逻辑）。
 * ⚠️ 真机校准点（doc §二 待校准 3 点）：开弹窗 click vs hover、是否需等重渲染、添加按钮选择器。
 */
function buildPopoverClosures() {
  const canOperate = (): boolean => collectOrders(document).length > 0
  const readOrderMarks = (orderId: string) => readOrderRowMarks(document, orderId)
  const openPopover = async (orderId: string): Promise<boolean> => {
    // 防串单：先关掉任何残留的单例弹窗（上一单），再点本单触发，轮询等弹窗出现。
    markCancelButton(getMarkPopover(document))?.click()
    await markDelay(150)
    if (!clickMarkTrigger(document, orderId)) return false
    const deadline = Date.now() + 1500
    while (Date.now() < deadline) {
      await markDelay(150)
      if (getMarkPopover(document) !== null) return true
    }
    return getMarkPopover(document) !== null
  }
  const readSelection = () => readPopoverSelection(getMarkPopover(document))
  const toggleMark = async (key: MarkLabelKey): Promise<void> => {
    clickMarkItem(getMarkPopover(document), key)
    await markDelay(250)
  }
  const confirm = async (): Promise<void> => {
    markConfirmButton(getMarkPopover(document))?.click()
    await markDelay(900) // 留店小秘保存 + vxe 行重渲染时间，回读校验才看到新标记（真机实测需 ~1s）
  }
  const cancel = async (): Promise<void> => {
    markCancelButton(getMarkPopover(document))?.click()
  }
  return { canOperate, readOrderMarks, openPopover, readSelection, toggleMark, confirm, cancel }
}

let manualMarkWaiting = 0 // >0：有手动打标在等锁 → 后台轮询本轮让位，保证人工操作优先（防被 8s 轮询饿死误报失败）

/** 等到弹窗空档（与后台打标轮询互斥，共用单例弹窗）；占用过久 → 放弃（留用户重试）。 */
async function acquireMark(timeoutMs = 12000): Promise<boolean> {
  manualMarkWaiting++
  try {
    const deadline = Date.now() + timeoutMs
    while (markBusy) {
      if (Date.now() > deadline) return false
      await markDelay(120)
    }
    markBusy = true
    return true
  } finally {
    manualMarkWaiting-- // 已抢到锁（markBusy=true 仍挡后台）或超时放弃 → 退出等待态
  }
}
function releaseMark(): void {
  markBusy = false
}

/**
 * 手动 force 打标：只处理本单，绕过受任务授权门控的 /inbox/mark/pending（人主动操作=授权）。
 * 与后台打标轮询共用单例弹窗 → markBusy 互斥；纯页面打标，服务端不留痕（postResult 空操作，决策#2）。
 * 返回 true=打标并回读校验通过（unrecognized 存在 且 DONE 不存在，§八.2）。
 */
async function runManualMarkOnce(orderId: string): Promise<boolean> {
  if (!(await acquireMark())) return false // 等不到弹窗空档（后台轮询占用过久）→ 判失败，留用户重试
  try {
    const c = buildPopoverClosures()
    if (!c.canOperate()) return false // 不在订单列表页 → 没法打标
    const r = await runMarkJobs({
      canOperate: c.canOperate,
      getQueue: async () => manualMarkQueue(orderId), // 客户端单单构造，绕过授权门控的 pending 拉取
      readOrderMarks: c.readOrderMarks,
      openPopover: c.openPopover,
      readPopoverSelection: c.readSelection,
      toggleMark: c.toggleMark,
      confirm: c.confirm,
      cancel: c.cancel,
      postResult: async () => {}, // 决策#2：纯页面打标，服务端不留痕
    })
    if (!r.applied) return false // 不在本页 / 弹窗未锚定 / runMarkJobs 校验未过 → 失败
    // §八.2 完整校验：回读订单行，确认 unrecognized 存在 且 DONE 不存在。
    const after = c.readOrderMarks(orderId)
    return Boolean(after && after.unrecognized && !after.done)
  } finally {
    releaseMark()
  }
}

function scheduleMark(seconds: number): void {
  if (markTimer !== undefined) clearTimeout(markTimer)
  markTimer = setTimeout(runMarkOnce, Math.max(2, seconds) * 1000)
}

async function runMarkOnce(): Promise<void> {
  // 共用单例弹窗，不能并发：上一轮在跑（markBusy）或有手动打标在等锁（manualMarkWaiting）→ 本轮让位。
  // 让位时仍重排定时器，维持后台轮询链（手动 runManualMarkOnce 不重排，故这里必须兜底，防轮询中断）。
  if (markBusy || manualMarkWaiting > 0) {
    scheduleMark(MARK_POLL_SECONDS)
    return
  }
  markBusy = true
  // ⚠️ P0：后台打标（写店小秘=真正的副作用）唯一判据 = 任务租约授权。未授权 → 不写店小秘，退避回探。
  // 服务端 /inbox/mark/pending 同样在未授权/范围外时返回空，双保险——即便这里漏 gate，也拉不到任务。
  const control = await askSW<ScrapeControl>({ type: 'FLOWER_GET_CONTROL' })
  if (!isAuthorized(control)) {
    markBusy = false
    scheduleMark(MARK_DISABLED_BACKOFF_SECONDS)
    return
  }
  try {
    // 共享弹窗操作：mark 队列回写 + AI 对账共用同一个全页单例弹窗，不能并发，故同一轮内串行复用这组闭包
    // （与手动 force 打标 runManualMarkOnce 同用 buildPopoverClosures，避免重复 DOM 时序逻辑）。
    const c = buildPopoverClosures()

    const r = await runMarkJobs({
      canOperate: c.canOperate,
      getQueue: async () =>
        (await askSW<{ jobs: MarkJobInput[] }>({ type: 'FLOWER_MARK_PULL', limit: MARK_BATCH_LIMIT }))?.jobs ?? [],
      readOrderMarks: c.readOrderMarks,
      openPopover: c.openPopover,
      readPopoverSelection: c.readSelection,
      toggleMark: c.toggleMark,
      confirm: c.confirm,
      cancel: c.cancel,
      postResult: async (orderId, action, ok, detail) => {
        await askSW({ type: 'FLOWER_MARK_RESULT', orderId, action, ok, detail })
      },
    })
    if (r.applied) toast(`已给 ${r.applied} 个订单回写店小秘标记`)
    if (r.failed) toast(`标记回写失败 ${r.failed} 单（将重试）`, false)

    // AI 识别状态对账：对本页可见单查库（以 DB ai_status 为权威）→ 据 desired_tag 同步店小秘标记。
    // 查库失败 → 该单 reconcile 返回 null → 不动标签；复核冲突 → desired=none → 冻结不动。
    const rec = await runReconcile({
      canOperate: c.canOperate,
      getOrders: () =>
        collectOrders(document)
          .map((hit) => ({
            order_id: hit.order.order_id,
            ai_done: Boolean(hit.order.ai_done),
            ai_unrecognized: Boolean(hit.order.ai_unrecognized),
          }))
          .filter((o) => o.order_id),
      reconcile: (orderId, aiDone, aiUnrecognized) =>
        askSW<ReconcileDecision | null>({
          type: 'FLOWER_AI_RECONCILE',
          orderId,
          aiDone,
          aiUnrecognized,
        }).then((d) => (d && typeof d.desired_tag === 'string' ? d : null)),
      readOrderMarks: c.readOrderMarks,
      openPopover: c.openPopover,
      readPopoverSelection: c.readSelection,
      toggleMark: c.toggleMark,
      confirm: c.confirm,
      cancel: c.cancel,
      writeLimit: MARK_BATCH_LIMIT,
      queryLimit: RECONCILE_QUERY_LIMIT,
    })
    if (rec.applied) toast(`AI 对账：已同步 ${rec.applied} 个订单店小秘标记`)
    if (rec.conflict) toast(`⚠ AI 对账：${rec.conflict} 单标记冲突，已转复核（见 Flower 配置端）`, false)
  } catch {
    /* 本轮失败忽略，下轮再来 */
  } finally {
    markBusy = false
    scheduleMark(MARK_POLL_SECONDS) // 后台轮询维持定时器（未授权时上面已退避回探）
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
scheduleAutoCycle(3) // 首轮稍候开跑（等表格渲染）；是否真抓由服务端开关决定
scheduleRescrape(RESCRAPE_POLL_SECONDS) // 定向重抓轮询（仅在搜索页实际处理）
scheduleMark(5) // 标记回写轮询（受 flower 开关 gate，仅 enabled 时写店小秘）
if (document.body) {
  new MutationObserver(scheduleInject).observe(document.body, { childList: true, subtree: true })
}
