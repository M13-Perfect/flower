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
} as const
