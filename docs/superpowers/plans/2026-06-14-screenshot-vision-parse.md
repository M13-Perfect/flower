# 订单截图视觉解析（screenshot_parser）— 后端完成 + UI 接线契约

> 2026-06-14。用户需求：截图也能解析→导出。选定方案：**视觉模型直解**（多模态，非 OCR）。
> 后端已落地（`screenshot_parser.py` + `tests/test_screenshot_parser.py`，5 passed，ruff clean，**未改 gpt_parser/ui_app**）。
> UI 的「选截图」按钮属 `ui_app.py`（CustomTkinter 线在改），按下面契约接。

## 背景：为什么需要

现有解析链只吃**文本字符串**（`订单备注` 框 / `导入` .txt/.json/.csv）。`order_importer` 遇图片直接报「二进制格式」，全项目无任何视觉/OCR 入口。所以截图当前**进不了解析**。本模块补这条路。

## 已落地（后端）

`screenshot_parser.parse_order_screenshot_with_gpt(image, *, bundle=None, api_key, model, provider, base_url, http_post, timeout, mime) -> ParseResult`

- `image`：截图**路径**或**原始字节**；内部 base64 成 data URL，随 OpenAI Responses `input_image`（或 DeepSeek `image_url`）送多模态模型。
- 复用 `gpt_parser` 的 HTTP 辅助（headers/post/extract/error）+ 与文本路径**相同的结构化输出 schema**：
  - **不传 `bundle`** → 旧 schema（`text/month/font/flower`）→ `gpt_parser.parse_gpt_payload` → **现有人工确认面板直接可用**。
  - **传 `bundle`**（`order_catalog.LibraryBundle`）→ catalog 动态枚举 schema（`material_key/font_key`）→ `parse_catalog_payload` 富化到具体素材。
- 返回的 `ParseResult` 与文本解析同构 → 复用现有 `_apply_parse_result`。

⚠️ **模型必须支持视觉**：默认 `DEFAULT_VISION_MODEL="gpt-4o-mini"`（可被 `model` 入参 / `OPENAI_VISION_MODEL` 环境变量覆盖）。**不要把文本用的 `gpt-5-nano` 之类纯文本模型传进来**，会拒图。

## 🔌 UI 接线契约（给 CustomTkinter 线）

在 `ui_app.py` 加一个「导入截图」按钮（放在「订单备注」action_row，与现有「导入/解析/清空」并列）：

```python
from screenshot_parser import parse_order_screenshot_with_gpt

def import_order_screenshot(self):
    path = filedialog.askopenfilename(
        title="导入订单截图",
        filetypes=[("图片", "*.png *.jpg *.jpeg *.webp *.bmp")],
    )
    if not path:
        return
    cfg = self._current_ai_config()           # 复用现有 AI 配置（key/provider/base_url）
    if not cfg.api_key:
        messagebox.showerror("缺少 API Key", "请先在设置里填 API Key（视觉解析必须联网）")
        return
    self.status_var.set("识别截图中...")
    run_background(
        self.root,
        lambda: parse_order_screenshot_with_gpt(
            path,
            api_key=cfg.api_key,
            model=cfg.model if _is_vision_model(cfg.model) else None,  # 非视觉模型则用默认视觉模型
            provider=cfg.provider,
            base_url=cfg.base_url,
            organization=cfg.organization,
            project=cfg.project,
            timeout=max(cfg.timeout, 30),
            # bundle=LibraryBundle.from_dirs(product.image_library_dirs, product.font_library_dirs),  # Phase 2 接 catalog 时再传
        ),
        self._apply_parse_result,             # 复用：填字段 + 建图层 + 重绘
        lambda exc: messagebox.showerror("截图识别失败", str(exc)),
    )
```

要点：
- 复用 `_current_ai_config()` 拿 key/provider（与文本解析同一套设置，用户只填一次 key）。
- 识别成功后 `_apply_parse_result` 已有的逻辑会填人工确认字段 + 建图层 → 之后「生成」导出，链路和文本一致。
- **视觉模型独立**：文本设置里的 model 多半是文本型；截图按钮要用视觉模型（传 `None` 用默认 `gpt-4o-mini`，或在设置里加个「视觉模型」字段）。

## 用户现在就能验证（不等 UI 按钮）

填好 key 后，在仓库根跑（替换 KEY 和截图路径）：

```powershell
$env:OPENAI_API_KEY="sk-..."
.\.venv-win\Scripts\python.exe -c "from screenshot_parser import parse_order_screenshot_with_gpt; r=parse_order_screenshot_with_gpt(r'C:\path\to\订单截图.png', model='gpt-4o-mini'); print(r)"
```

打印出的 `ParseResult` 若有 text/month/font/flower，即视觉解析通。

## 待办
- UI 线在 `ui_app.py` 加「导入截图」按钮（上面契约）。
- 设置里可选加「视觉模型」字段（默认 gpt-4o-mini），与文本模型分开。
- DeepSeek 视觉：`_screenshot_with_deepseek` 已写（`deepseek-vl2` 默认），需用户验证该模型在其账号可用。
