// 店小秘订单列表页（vxe-table）选择器，已按真实「待处理」筛选页 DOM 校准。
// 结构要点：一个订单 = 两行 <tr>，靠 rowid 配对——
//   明细行 tr[rowid="X"]：订单号(.orderCode) + 定制信息(.order-sku__attr) + SKU。
//   表头行 tr[rowid="X_header"]：标记(含 AI未识别) + 店铺。
// vxe 把列拆成左固定/主/右固定多张表，同 rowid 行会重复 → 提取器按 rowid 去重。
// 改版维护只动本文件。

export const SELECTORS = {
  /** 明细行里订单号所在单元格（也用作注入按钮的锚点）。 */
  orderCodeCell: '.orderCode',
  /** 定制信息每一行：文本形如「Label  ：Value」。 */
  attrLines: '.order-sku__attr > div',
  /** 表头行里的店铺单元格（col_115，右对齐文本，如「Etsy：Thai-1」）。 */
  shopCell: 'td[colid="col_115"]',
  /** SKU / listing id。 */
  skuName: 'a.order-sku__name',
  /** 「AI未识别」标记：酒红底档案图标（与该标记 1:1）。 */
  aiMarkIcon: 'i.icon_brush_bill',
  /** 兜底：酒红色标记块（rgb(226,36,127)）。 */
  aiMarkBlock: '.order-mark-block[style*="226, 36, 127"]',
  /** 定制项 Label 与 Value 之间的全角冒号。 */
  attrColon: '：',

  // ── 行项目（一单多件）相关，按真实「全部订单」列表页校准 ──
  // 订单明细单元格里，每个目标商品 = 一个 `.order-sku` 块；同一订单可有多块（混单/多盒子）。
  /** 单个行项目容器（一块 = 一行商品）。 */
  skuBlock: '.order-sku',
  /** 行项目件数（`<span class="order-sku__symbol">x</span><span class="order-sku__quantity">1</span>`，可能缺省）。 */
  skuQuantity: '.order-sku__quantity',
  /** 行项目单价文本（如「USD 79.50」，进 item.extras 便于「其他商品」展示）。 */
  skuPrice: '.order-sku__price',
  /** 行项目缩略图（进 item.extras）。 */
  skuImage: '.order-sku__image img',
  /** 订单实时状态单元格（col_317，首个 div 文本，如「已退款 / 风控中 / 已发货」）；退款拦截用。 */
  orderState: '.orderState',
  /** 订单时间轴每项（col_315，形如「付款：2026-06-19 02:25」；取「付款」那项作付款时间）。 */
  orderTimeItem: '.order-time-list .order-time-list-item',

  // ── 店小秘「搜索订单」页（Ant Design 搜索表单，结果表仍是 vxe-table）按真实样例校准 ──
  // 定向重抓（option B）：在搜索框输订单号 → 提交 → 结果用现有 collectOrders 解析。
  /** 订单号搜索输入框（placeholder「多个订单号间用逗号或空格隔开」，本就按订单号搜，无需切类型）。 */
  searchInput: '#orderSearchInput',
  /** 搜索输入框兜底选择器（id 万一改版）。 */
  searchInputFallback: 'input[name="tableSearchInput"]',
  /** 搜索提交按钮（ant 主按钮 type=submit，文本「搜索」；按文本二次确认）。 */
  searchSubmit: 'button.ant-btn-primary[type="submit"]',

  // ── 标记回写（给店小秘订单打 AI未识别/AI已处理 自定义标记）按真实 DOM 校准（2026-06-20 只读勘查）──
  // ⚠️ 识别某标记靠其内 i 的图标 class，**不靠颜色**：酒红 rgb(226,36,127) 被 AI未识别/加急运输/T21-worst 共用。
  /** 订单行的自定义标记区（在表头行 tr[rowid="X_header"] 内的 .orderBagInfo 里）；末尾空 .order-mark-block ≈ 添加按钮。 */
  orderMarkArea: '.bag-info-coustom',
  /** 已打标记块（一块=一标记）。 */
  orderMarkBlock: '.order-mark-block',
  /** 订单行上「AI未识别」已打的判据图标（唯一）。 */
  appliedUnrecognizedIcon: 'i.icon_brush_bill',
  /** 订单行上「AI已处理」已打的判据图标（唯一）。 */
  appliedDoneIcon: 'i.icon_change_order',
  /** 「设置自定义标记」弹窗（Ant Popover，全页单例，点某单标记区即锚到该单）。 */
  markPopover: '.markPopover',
  /** 弹窗内每个标记一行。 */
  markRemarkItem: '.remark-item',
  /** 标记行的 label 文字（按文字精确匹配 MARK_LABELS）。 */
  markRemarkText: '.remark-item__text',
  /** 标记行右侧操作区（恒含 停用/编辑 图标；选中行额外多一个对勾 i，实测 icon_support）。 */
  markRemarkAction: '.remark-item__action',
  /** 弹窗「确定」按钮（提交本单标记改动）。 */
  markConfirm: '.markPopover__header button.ant-btn-primary',
  /** 弹窗「取消」按钮。 */
  markCancel: '.markPopover__header button.ant-btn-default',
  /** 弹窗标记过滤搜索框（可选用以缩小点击目标）。 */
  markFilter: '.markPopover__filter input.ant-input',

  // ── 翻页（vxe-pager mini-d-pager：仅 上一页/下一页 + 总数/区间，无页码按钮）按真实「待处理」页校准 ──
  // 自动翻页用：每页 100 条、虚拟滚动（要滚到底才渲染满本页）；末页时按钮加 is--disabled。
  /** 下一页按钮（末页含 is--disabled）。 */
  pagerNextBtn: 'button.vxe-pager--next-btn',
  /** 上一页按钮（首页含 is--disabled）。 */
  pagerPrevBtn: 'button.vxe-pager--prev-btn',
  /** 总记录数文本（「共 165 条记录」）。 */
  pagerTotal: '.vxe-pager--total',
  /** 当前区间文本（「第101-165条，」）。 */
  pagerRange: '.vxe-pager--left-wrapper',
  /** vxe 主表体滚动容器（虚拟滚动：滚到底才渲染满本页 100 行）。 */
  tableBodyWrapper: '.vxe-table--body-wrapper',
} as const

/** vxe 按钮禁用态标记（首页的上一页 / 末页的下一页）。 */
export const PAGER_DISABLED_CLASS = 'is--disabled'

/** 标记 label（店小秘「设置自定义标记」里的确切文字，2026-06-20 勘查确认）。 */
export const MARK_LABELS = { unrecognized: 'AI未识别', done: 'AI已处理' } as const

/**
 * 选中态对勾图标（白名单）：标记行 .remark-item__action 内出现其一即视为「已选中」。
 * 实测 = icon_support（2026-06-20 勘查）。用白名单而非「排除 icon_block/icon_edit2」黑名单——
 * 避免店小秘日后在操作区新增无关图标被误判为已选。⚠️ 真机校准点：对勾确切 class（见 docs §二）。
 */
export const MARK_SELECTED_ICONS = ['icon_support'] as const

/** 弹窗「确定」按钮文本（多候选时二次确认）。 */
export const MARK_CONFIRM_TEXT = '确定'

/** 搜索提交按钮的文本（用于在多个候选按钮里挑出「搜索」那个）。 */
export const SEARCH_SUBMIT_TEXT = '搜索'

/** 时间轴里付款行的标签前缀。 */
export const PAID_LABEL = '付款'
