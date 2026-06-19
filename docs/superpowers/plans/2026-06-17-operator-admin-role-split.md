# 操作员 / 管理员 双视图（纯桌面端）

> 状态：设计已拍板（2026-06-17），待实现。范围 = Tkinter 桌面 App（`birth_flower_mvp.py` + `ui_app.py`）。
> 配 `AGENTS.md` 顶部「当前事实」与 `CURRENT_TASKS.md` 一起读。

## 0. 决策摘要

- **继续纯桌面端**（Tkinter/CustomTkinter）。**web 迁移暂缓**——仅当出现**远程/多地操作员**（需要真服务端登录）才重启 web 方案。
- 把现在挤在一个「功能区」里的东西，按角色拆成 **操作员视图 / 管理员视图**。
- **唯一上锁** = 「**提示词配置**」（背景提示词 + 提取/字段规则 + 校验规则，即驱动 AI 识别那块）→ 仅管理员、进它才要**密码**；**其余全部操作权限归操作员**（含画布编辑、加/删图层、换素材、资源库、输出设置、新建产品）。
- **启动无登录页**：直接进操作员态（全权）；只有打开「提示词配置」才弹密码。

> 注（2026-06-17 用户拍板）：明确"仅提示词配置为管理员权限"。若日后想把图层模板默认几何/绑定/输出规则也收回管理员，再收窄即可（低成本）。

## 1. Goal（目标）

让非开发者操作员能安全跑量产：粘单 → 解析 → **在画布上微调本单**（救失败素材）→ 生成；唯独把"会影响所有订单、且属 IP"的**提示词配置**锁在管理员后面，防误改。**现在就有操作员在用**，这是本轮第一动力。

## 2. 权限边界（2026-06-17 定档：操作员全权，唯一锁 = 提示词配置）

- 操作员与管理员**用同一个画布编辑器，能力零差异**：选层、移动/缩放/旋转、改文字内容/字号、加/删图层、换素材变体（已绑定变体内）、实时预览（== 导出）。
- **唯一需要管理员密码的是「提示词配置」**（背景提示词 + 提取/字段规则 + 校验规则）——它驱动 AI 识别、改一处影响所有订单，也是 IP，故唯独它上锁。
- 其余**全部操作权限归操作员**（含资源库、输出设置、新建产品、图层模板几何/绑定）。
- 数据卫生原则（非锁边界）：操作员的**逐单画布微调**写进**本单 document**，不静默回写 template。
- **红线：锁只盖「提示词配置」，从不盖画布。**

| 能力 | 操作员 | 管理员 |
|---|:--:|:--:|
| 粘单 / 解析 / 复核字段 | ✓ | ✓ |
| 画布编辑：选层 · 移动/缩放/旋转 · 改字 · 换素材（已绑定变体内）| ✓ | ✓ |
| 加 / 删图层 | ✓ | ✓ |
| 资源库 上传/扫描 · 输出设置 · 新建产品 · 图层模板几何/绑定 | ✓ | ✓ |
| 生成 PNG / SVG / DXF | ✓ | ✓ |
| **提示词配置**（背景词 + 提取/字段规则 + 校验规则）| **✗** | **✓ 需密码** |

## 3. Current code findings（现状，可复用）

- **画布编辑器雏形已在**：`实时画板`（`preview_canvas` + `_apply_canvas_fit` WYSIWYG）、图层面板（增量渲染、拖柄拖序、右键菜单、位置/尺寸编辑 `_apply_layer_production`）。→ 这就是"共享画布编辑器"，两视图直接共用。
- **配置锁机制已在**：`self._locked_widgets` + `_register_lock`/`_prune_locked` + `_ctk_card(locked=True)`（卡头 🔒）+ `config_locked`（订单备注框不入锁）。**当前只 disable、无密码（原 P4）**。→ 本轮给它补**密码**，并把所有配置控件归到锁下。
- 早先的 ASCII 草图里 `提示词配置 🔒 [解锁配置]` 即此机制的目标形态。
- 产品列（`_render_product_rail`/`_switch_product`）已在 → 管理员可新建/切换；操作员可切换、不可新建（按开放项定）。

## 4. Proposed architecture（落到 ui_app.py 的改法，方向）

1. **启动无登录页**：直接进操作员态（全权）。无重型登录/角色切换页；只在打开「提示词配置」时校验密码。
2. **提示词配置卡单独上锁**：点开 → 密码对话框 → 通过才显内容/允许编辑（复用 `_register_lock` + `_ctk_card(locked=True)` **只盖这一张卡**）。校验失败不解锁。
3. 其余控件（画布、图层面板、资源库、输出设置、新建产品、模板几何/绑定）**都不入锁**。
4. **画布编辑器**（实时画板 + 图层面板：选层/拖动/缩放/改字/加删图层/换素材）保持现状、全程可用。
5. 操作员主面板 = 订单粘贴/解析 + 识别结果复核 + 画布 + 生成（PNG/SVG/DXF）；「提示词配置」作为一张锁着的卡放在配置区。
6. **换素材**：候选只列该图层**已绑定的变体**（不列整库）。

## 5. 密码锁说明（别过度造）

- 本地密码门 = **防误操作**，不是真安全（有文件/源码访问就能绕）。够用即可。
- 密码存 config 的**哈希**，不存明文；校验失败不解锁。
- **不要**为此引入服务端/真账号体系——那是 web 方案的触发点，现在不做。

## 6. Data model changes

- 可能在 `AppConfig` 加 `admin_password_hash`（+ 迁移：无则首次设置或留空 = 不锁）。
- 不改 document/template schema（document-vs-template 分层已存在）。

## 7. API changes

- 无（纯桌面 in-process）。

## 8. Test plan

- 纯逻辑可测：角色切换状态机、密码校验（hash 往返、错误不解锁）、锁覆盖清单（operator 态配置控件全 disabled/hidden、画布控件全 enabled）。
- Tkinter 交互（解锁弹窗、隐藏/禁用、画布编辑）需**真机手测**（沿用项目惯例）。
- 回归红线：operator 改画布只动 document、生成字节与现状一致（金标不破）。

## 9. Risks / 避坑

- 本地密码非真安全（已注明）。
- **别把"画布编辑"误锁进配置抽屉**（操作员就救不了素材了）——本设计头号红线。
- 预览 == 导出别破：文字仍走 `fit_text_box` 单一大脑。
- 改完 Python **完全关掉 App 重开**再测（旧进程缓存模块）。
- CTkOptionMenu / ctk.CTk 既有坑（见 `AGENTS.md`）继续适用。

## 10. Rollback

- 角色/密码是新增的 UI 状态层，关掉 = 回到当前单视图；不动导出/批量/金标路径，低风险。

## 11. 已定（2026-06-17 用户答复）

- 操作员**可加/删图层**（属"全部操作权限"）。
- **换素材 = 只在该图层已绑定的变体内换**（不开放整库挑选）。
- **启动无登录页**：直接进操作员态；只有进「提示词配置」才要管理员密码。
- 锁范围 = **仅提示词配置**；其余操作全归操作员。

## 12. web 分支现状与决策（2026-06-17 体检后存档 —— **web 暂挂**）

**状态：web 暂挂**,专注桌面端。分支 `claude/web-editor`（独立 worktree `.worktrees\web-editor`,已推 origin）,起点 = 最新 main(`85f172e`)。

**体检结论：脚手架完整,但是一条落后桌面端几个月、且已部分"用 JS 重写引擎"的支线。**

已有（比预期完整）：
- 前端 `apps/desktop`：React 19 + **Fabric 7**(不是 Konva) + Vite 7 + Electron 39 + Vitest；`FabricCanvas` + `canvasViewport`(缩放平移已起步) + `canvasConstraints` + `layerFabricModel` + typed `client` + `exportPipeline` + `orderWorkflow` + `GlyphPicker`,多数带 `.test.ts`。
- 后端 `services/api`：真 FastAPI(`main.py`)：`/health` `/fonts*` `/settings/paths` `/orders/parse` `/templates/apply` `/exports/dxf` `/outputs/save`,CORS + 错误信封 + pytest。
- `npm run dev`(`tools/dev.mjs`) 同起 FastAPI + Vite；前端默认连 `127.0.0.1:8765`。（**未实跑验证**,需 `npm install` + python 依赖。）

**两个硬伤（决定 web 复工第一步不是画 UI、而是"引擎归一"）：**
1. **SVG/PNG 是前端 TS 渲染的,绕开 Python**：`exportPipeline.ts` 用 `<text font-family/font-size>` 靠浏览器排版、再用 canvas 栅格化 PNG；**只有 DXF 发去 Python**。→ 完全绕过 `fit_text_box`/字形轮廓/镂空/加粗,web 的 SVG/PNG 必和桌面对不上、且是字体依赖而非雕刻轮廓。✅ 但 `services/api/app/domain/exports/{svg,png}.py` 已存在,只是 `main.py` 没暴露、前端没调 → 修法 = 加 `/exports/svg` `/exports/png` 接口、前端弃 `exportPipeline.ts` 的 TS 渲染改调 Python。
2. **`services/api` 引擎落后根目录几个月**：根目录这些桌面在用的模块,`services/api` 下**全无**：`text_layout.py`(fit_text_box)、`material_library.py`、`order_catalog.py`、`config_store.py`、`production.py`、`gpt_parser.py`、`screenshot_parser.py`、`glyph_service.py`。web 的 `/orders/parse` 是旧本地解析,无素材库枚举/GPT/截图。

**web 复工时的正确第一步 = 引擎归一（不是堆 UI）：**
- 把根目录那批功能搬进 `services/api`,让**桌面与 web 共用同一套 Python 引擎**（顺带消除当前根目录 vs services/api 的双轨重复）。
- 暴露并改用 Python 的 svg/png 导出,删 `exportPipeline.ts` 的 TS 渲染路径。
- 之后才是 web 端 UI（角色分离同样适用：共享画布 + 仅提示词配置上锁）。
- 前端是 **Fabric**(非 Konva)；缩放/平移/视图变换在 web 端近乎白送(`canvasViewport` 已起步)。

估时（届时,引擎归一**之后**）：P0 去风险 ~1 周 / P1 操作员可编辑画布 ~3–5 周 / P2 管理员配置 ~2–3 周 / P3 打包+认证 ~1–2 周。**外加引擎归一本身的工作量(8 个根模块搬进 services/api + svg/png 接口化 + 删 TS 渲染),这是 web 复工的前置。**

> 注：本节存于桌面线(`claude/desktop-tkinter`/主工作树)。web 分支自身的工作树是 `85f172e` 旧版、看不到本次更新；web 复工时需把这几份 handoff 文档同步/cherry-pick 过去。

## 13. Milestones（桌面端本方向）

1. 角色状态 + 密码门（解锁/上锁）。
2. 配置控件全收进受锁抽屉；画布编辑器确认不入锁。
3. 操作员面板精简（粘单/解析/复核/画布/生成）。
4. 锁覆盖清单单测 + 真机手测。
5. 更新 `AGENTS.md` / `CURRENT_TASKS.md`。
