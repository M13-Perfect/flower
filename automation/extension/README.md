# Flower 取单扩展（Chrome MV3）

店小秘订单页 → 一键发送当前订单到本地收单服务（automation 一期）。TypeScript + Vite（@crxjs）+ Vitest。

## 安装 / 构建

```powershell
cd automation\extension
npm install
npm run build      # 产物在 dist/，用于「加载已解压的扩展程序」
npm test           # Vitest：提取器单测（jsdom 夹具）
npm run typecheck  # tsc 类型检查
```

## 在 Chrome 加载

1. 先启动本地服务（见 `../inbox-service/README.md`，监听 127.0.0.1:8770）。
2. Chrome → 扩展程序 → 打开「开发者模式」→「加载已解压的扩展程序」→ 选 `automation/extension/dist`。
3. 打开店小秘订单详情页 → 右下角点「发送到 Flower」。popup 里有本地服务健康灯。

## 结构

- `src/content/content.ts` — 注入按钮，点了就 `extractOrder(document)` → 发消息给 worker。
- `src/extractor/extractor.ts` — **纯函数**提取器（可单测，无 chrome.*）；`selectors.ts` 集中所有选择器。
- `src/worker/service-worker.ts` + `client.ts` — 收消息 → POST `127.0.0.1:8770/inbox/orders`。
- `src/popup/` — 健康灯 + 用法提示。
- `src/fixtures/*.html` — Vitest 用的合成订单页夹具。

## ⚠️ 选择器待用真实 DOM 校准

`selectors.ts` 目前是占位/启发式（类名 + 按标签锚定兜底）。请把一个**真实店小秘订单详情页**另存为完整
HTML（脱敏）放进 `src/fixtures/`，据此校准 `selectors.ts` 并补一个真实夹具断言，提取才可靠。
