# 图层素材库系统 ExecPlan（Product → 素材库 → 素材 → 图层）

> **For agentic workers:** REQUIRED SUB-SKILL: 用 superpowers:executing-plans / subagent-driven-development 按 Task 逐条实现。步骤用 `- [ ]` 跟踪。
> **状态：设计已定稿，待实现。** 本文档由 2026-06-14 新需求对话产出；当时只写文档、未改代码（用户选择「先出 ExecPlan」）。
> 配套阅读：`PROJECT_INDEX.md`、`CURRENT_TASKS.md`、`AGENTS.md`。导出/WYSIWYG 细节见 `docs/superpowers/plans/2026-06-13-dxf-export-progress.md`；文字排版统一见记忆 `flower-text-layout-unified`。

**Goal:** 把当前「单产品 birth-flower + 全局单素材库 + month/flower 定位 + 全局生产参数」演进为 **Product（产品）→ Material Library（素材库）→ Material（素材，带 key/别名/标签/默认生产参数）→ Layer（图层级引用 + 生产参数 override）** 的通用体系。素材不再局限于花朵、字体不再局限于固定编号；每个图层可独立挂库、生产参数随图层变；订单解析改为「把库目录注入 GPT、用动态枚举校验 material_key」，本地规则零硬编码。

**Architecture:** 保持生产现实——Tkinter 桌面 `ui_app.py` + 共享后端 `services/api`（in-process import）。**演进兼容**：birth-flower 作为「产品 0」，month/flower 降级为该产品素材的标签（tag），现有金标测试 / 批量模板 / DXF 导出字节不破。数据模型从一开始 **Product-aware**（避免日后二次迁移），但「左侧产品切换器 UI」放到后期阶段。

**Tech Stack:** Python 3.12（`.venv-win`）、Tkinter、dataclasses、pydantic v2（后端 schema）、ezdxf/svgwrite/Pillow、pytest。

---

## 1. 用户决策（2026-06-14 已确认）

| # | 决策点 | 选择 |
|---|---|---|
| 1 | birth-flower 链路与新模型如何共存 | **演进兼容**：month/flower 作为「birth-flower 库」内部标签，叠加通用「素材库+素材key」。**补充**：后期窗口左侧加产品切换器，每个窗口 = 一个产品。 |
| 2 | 人工确认字段「月份」如何泛化 | **素材选择器取代**：用「素材库 + 素材」可搜索选择器取代「月份 + 花朵」；month 降级为素材标签。 |
| 3 | 「素材库」怎么定义 | **文件夹 + 可选 `library.json` 清单**：纯文件夹零配置可用；清单解锁 key/别名/标签/per-素材默认生产参数。 |
| 4 | 本轮做到哪一步 | **先出 ExecPlan 文档**（= 本文件），不改代码。 |

## 2. 现状诊断（代码事实，已验证）

| 维度 | 现状 | 代码位置 |
|---|---|---|
| 素材/字体库 | 全局单库：`flower_dir` + `font_source` 一份，所有图层共享 | `config_store.py:35`、`ui_app.py:530`、`asset_resolver.scan_flower_assets/scan_font_assets` |
| 定位键 | `month(1-12) + flower(1-2)` 反查花朵；`find_flower_asset(dir, month, flower)` | `asset_resolver.py:90`、`ui_app._select_flower_by_current_fields`（约 2427） |
| 人工确认字段 | 内容 / 月份(Spinbox 1-12) / 字体(1-8) / 花朵(1-2) | `ui_app.py:801` 起，`month_var/font_var/flower_var`（约 522） |
| 生产参数 | 全局一份 `EngravingLayout`，仅在「添加图层」时作初值，之后图层各自管几何 | `models.py:44`、`config_store.py:41`、`ui_app.layout_vars`（约 512）、`_set_layout_vars`（约 1168） |
| 图层素材引用 | `ImageLayer.material_id/material_name`（仅显示用），无「引用哪个库」字段；`TextLayer.font_path` 直接存绝对路径 | `models.py:129/141` |
| 解析 schema | GPT 输出硬约束 `month 1-12 / font 1-8 / flower 1-2` | `gpt_parser.py:18` ORDER_REMARK_SCHEMA |
| 解析→文档 | ParseResult 只回填 UI 字段（month/font/flower），UI 再用 month+flower 反查素材；`selected_flower_asset` 字段当前未被 UI 用 | `ui_app.py:1405` 起 |

**结论：** 「全局单库 + month 为核心定位键 + 生产参数全局一份」三点全部成立。`Layer` 基类注释已是「Photoshop 风格图层」，README 里的 "PSD" 仅指 gitignore 客户文件，不是功能——本需求即把这套图层体系做成真正的「每层可挂库」系统。

## 3. 目标领域模型

```
Workspace（应用）
└── Product（产品，NEW）                  ← 每个窗口=一个产品；左侧产品切换器（后期）
    ├── image_libraries: [MaterialLibrary]   该产品可用的图像素材库
    ├── font_libraries:  [MaterialLibrary]   该产品可用的字体库
    ├── defaults: ProductionParams           产品级默认生产参数（承载现 EngravingLayout）
    ├── manual_fields: [FieldSpec]           该产品人工确认面板显示哪些字段（数据驱动）
    └── Document（多图层文档）
        └── Layer[]
            ├── ImageLayer: library_id + material_key + production(override?)
            └── TextLayer:  font_library_id + font_key + production(override?)
```

### 3.1 数据结构（新增 / 改动，按文件）

**`material_library.py`（NEW 模块）**
```python
@dataclass(frozen=True)
class MaterialEntry:
    key: str                       # 库内唯一稳定 slug，如 "march-daffodil"
    name: str                      # 显示名
    path: Path                     # 素材文件
    aliases: tuple[str, ...] = ()  # 解析别名（"水仙","daffodil","三月"...）
    tags: Mapping[str, Any] = field(default_factory=dict)  # birth-flower 兼容：{"month":3,"flower":1}
    defaults: ProductionParams | None = None  # per-素材默认生产参数（覆盖库默认）
    kind: str = "image"            # image | font
    is_vector_safe: bool = True
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class MaterialLibrary:
    id: str                        # 库 id，如 "birth-flowers"
    name: str
    kind: str                      # image | font
    root: Path                     # 库文件夹
    defaults: ProductionParams | None = None  # 库级默认生产参数
    entries: tuple[MaterialEntry, ...] = ()

    def by_key(self, key: str) -> MaterialEntry | None: ...
    def catalog(self) -> "Catalog": ...   # 解析器用的扁平视图

@dataclass(frozen=True)
class Catalog:
    """解析器/GPT 面向的库目录视图：key + 显示名 + 别名 + 标签。"""
    library_id: str
    items: tuple[dict, ...]   # {"key","name","aliases","tags"}
    def keys(self) -> set[str]: ...
```

**`production.py`（NEW 或并入 models）—— 生产参数容器**
```python
@dataclass(frozen=True)
class ProductionParams:
    """单元素生产参数；所有字段可选，None=回落上一层。"""
    x: float | None = None
    y: float | None = None
    width: float | None = None
    height: float | None = None
    rotation: float | None = None
    font_size: int | None = None          # 文本类素材
    lock_aspect_ratio: bool | None = None
    # 预留导出相关：fill/stroke/层色等后续按产品扩展
    def merge_onto(self, base: "ProductionParams") -> "ProductionParams": ...
```
> 现 `EngravingLayout`（canvas_width/height + flower_*/text_*）**保留**，作为 birth-flower 产品的 `defaults` 容器与既有金标/批量入口；新 `ProductionParams` 是「单图层/单素材」粒度，二者经解析器桥接（见 §6）。

**`models.py`（改动）**
```python
@dataclass
class ImageLayer(Layer):
    path: Path | None = None
    material_id: str = ""          # 保留（显示）
    material_name: str = ""        # 保留
    library_id: str = ""           # NEW：引用哪个素材库
    material_key: str = ""         # NEW：库内素材 key
    production: ProductionParams | None = None  # NEW：图层级生产参数 override
    ...

@dataclass
class TextLayer(Layer):
    font_path: Path | None = None  # 保留
    font_library_id: str = ""      # NEW
    font_key: str = ""             # NEW
    production: ProductionParams | None = None  # NEW
    ...
```
> 新字段全部带默认空值 → 旧 Document 反序列化不破；`__post_init__` 可从旧 `material_id`/`font_path` 迁移回填 `material_key`/`font_key`（best-effort）。

**`config_store.py`（改动）`AppConfig`**
```python
@dataclass
class AppConfig:
    ...
    products: list[ProductConfig] = field(default_factory=list)  # NEW
    active_product_id: str = "birth-flower-card"                  # NEW
    # 旧 flower_dir/font_source/layout_defaults 保留，迁移期映射进 products[0]
```
`ProductConfig`：`id / name / image_library_dirs:[Path] / font_library_dirs:[Path] / defaults(EngravingLayout) / manual_fields`。
**迁移：** 启动时若 `products` 为空，用现 `flower_dir`→一个 image 库、`font_source`→一个 font 库、`layout_defaults`→`defaults`，合成「产品 0 = birth-flower-card」。用户零感知。

### 3.2 `library.json` 清单 schema（可选，放库文件夹根）
```json
{
  "id": "birth-flowers",
  "name": "生日花",
  "kind": "image",
  "version": 1,
  "defaults": { "x": 310, "y": 40, "width": 1060, "height": 1060, "lock_aspect_ratio": true },
  "materials": [
    {
      "key": "march-daffodil",
      "name": "Daffodil",
      "file": "March_Daffodil.svg",
      "aliases": ["daffodil", "水仙", "三月", "narcissus"],
      "tags": { "month": 3, "flower": 1 },
      "defaults": { "width": 1040 }
    }
  ]
}
```
**零配置回落：** 无 `library.json` → 扫文件夹，文件名推 `key`（复用 `asset_resolver._asset_key`）。对 birth-flower 库，复用现 `scan_flower_assets` 的月份/花朵识别逻辑自动补 `tags.month/flower`，使旧链路不依赖手写清单也能跑。`asset_resolver.scan_flower_assets/scan_font_assets` → 重构为「无清单时的 MaterialLibrary 构造器」，对外签名保留以免破测试。

## 4. 人工确认字段重构（决策 2）

| 现在 | 改为 | 说明 |
|---|---|---|
| 内容 | 内容 | 不变（雕刻文字 / 姓名） |
| **月份(1-12)** + **花朵(1-2)** | **素材库** + **素材** | 素材=可搜索选择器，候选来自所选库 catalog（显示名）；month 作为标签/筛选 chip 展示，不再是独立必填字段 |
| **字体(1-8)** | **字体库** + **字体** | 同模式，摆脱固定 1-8 编号 |
| （数量等） | 不变 | — |

- 字段集**数据驱动**：由 `Product.manual_fields` 声明，别的产品可声明不同字段。
- birth-flower 产品默认字段：内容 / 素材库 / 素材 / 字体库 / 字体 / 数量。
- 「素材」选择器选中后 → 在选中图层（或新建图层）写 `library_id + material_key`，并按 §5 解析生产参数。

## 5. 生产参数随图层（决策 1+3）

**解析优先级（渲染/导出时自顶向下回落）：**
```
layer.production（图层 override）
  ↳ material.defaults（素材级，来自 library.json）
    ↳ library.defaults（库级）
      ↳ product.defaults（EngravingLayout，产品级）
        ↳ 全局硬默认（EngravingLayout()）
```
- 选中图层时，属性面板展示**该图层**的生产参数（几何/字号/导出相关）可编辑；编辑即写 `layer.production`。
- 「添加素材」时用上面链路求得初值 seed 进新图层（取代现在只用全局 `layout_vars`）。
- **WYSIWYG 红线：** 求得的几何最终仍必须经现有 `desktop_export._apply_canvas_fit` / 批量 `workflow._apply_layout_overrides` 的 contain-fit 落进 DXF/SVG，**不得旁路**，否则破坏「预览==导出」（见记忆 `flower-dxf-export` / `flower-text-layout-unified`）。新参数只改「初值从哪来」，不改 fit 管线。

## 6. 订单解析 / GPT 对接（决策：本地不写死）

**核心：把库 catalog 注入 GPT，让它把订单文本映射到一个 `material_key`；输出用「该库真实 key 集合」做动态枚举校验。**

- **`models.ParseResult` 新增**（旧字段保留兼容）：
  `material_library_id / material_key / font_library_id / font_key`。
  birth-flower 路径下，`month/flower` 由命中素材的 `tags` 反推回填（兼容旧 UI / 金标）。
- **`gpt_parser.py` 改动：**
  - `ORDER_REMARK_SCHEMA` 由「写死 month 1-12 / font 1-8 / flower 1-2」改为「`material_key`/`font_key` = 枚举（运行时由当前产品各库 catalog 动态生成）+ `null`」。
  - prompt 注入：当前产品、各库的 `catalog`（key + 显示名 + 别名 + 标签）。让模型「在给定目录里选一个 key，选不出填 null 并写中文 warning」。
  - 校验层：模型回的 key ∉ catalog → 置 null + warning（不接受幻觉 key）。
- **`local_order_parser.py` / `birth_flower_parser.py`：** 保留作离线兜底；改为「先按 alias/月份命中 catalog → material_key」，命不中再走旧 month 逻辑。**不新增硬编码月份表**，月份信息走库 `tags`。
- **ParseResult → Document：** 新增映射「`material_key` → `library.by_key()` → MaterialEntry.path → `add_image_layer(... library_id, material_key, production=seed)`」；`font_key` 同理落 TextLayer。取代现在「month+flower 反查」。

> 说明：GPT key 与 `ORDER_REMARK_SCHEMA` 的真实接入在 Phase 3，本轮只定 schema 形状；不放真实 API key。

## 7. 演进兼容红线（不许破）

1. 金标 / 批量字节：`tests`、`services/api/tests` 现 **293 passed**（1 个既有无关红 `test_physical_size`，见 CURRENT_TASKS，**勿在本需求里顺手改**）。新字段一律可选默认，金标/批量入口（`layout=None`）走旧路径，输出字节不变。
2. `asset_resolver.scan_flower_assets/scan_font_assets` 对外签名保留，测试 `test_asset_resolver.py` 不破。
3. 旧 Document JSON 反序列化：新增字段默认空 + `__post_init__` 迁移，旧存档可开。
4. 配置迁移：旧 `birth_flower_config.json`（flower_dir/font_source/layout_defaults）自动合成产品 0，用户零操作。
5. WYSIWYG / 导出朝向：不动 `_apply_canvas_fit` / `dxf.py` / `svg.py` 的 fit 与 Y 翻转逻辑（朝向问题是独立未解项，见 AGENTS「已知问题」）。

## 8. 分阶段实现计划（Task by Task）

> 每个 Task 先写失败测试 → 实现 → 跑测试。命令：
> `$env:PYTHONPATH=".;services\api"; .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`
> 改完 Python **必须完全关掉 App 重开**再手测。

### Task 1：数据模型 + 素材库基础层（Phase 1，无 UI）
**Files:** 新增 `material_library.py`、`production.py`；改 `models.py`、`asset_resolver.py`、`config_store.py`；新增 `tests/test_material_library.py`、`tests/test_production_params.py`。
- [x] **Step 1（红）** 写测试：`MaterialLibrary.from_folder()` 无清单时扫 birth-flower 文件夹得到带 `tags.month/flower` 的 entries；有 `library.json` 时优先用清单；`by_key()` / `catalog()` 正确；`ProductionParams.merge_onto` 回落顺序正确。✅ `tests/test_production_params.py`(7) + `tests/test_material_library.py`(6)。
- [x] **Step 2** 实现 `material_library.py`（清单加载 + 零配置回落，birth-flower 复用 `scan_flower_assets` 逻辑）、`production.py`（`ProductionParams` + 回落 merge）。✅ 13 passed + ruff clean。中文别名匹配用 `str.isalnum()` 归一化（不可借 ASCII-only 的 `_compact_name`）。**纯新增文件，未改任何现有文件。**
- [x] **Step 3** `models.py`：`ImageLayer` 加 `library_id/material_key/production`；`TextLayer` 加 `font_library_id/font_key/production`；`__post_init__` 迁移旧字段（material_id→material_key、font_path→font_key、production 容忍 dict）。✅ `tests/test_layer_material_fields.py`(6)。
- [x] **Step 4** `config_store.py`：`AppConfig` 加 `products/active_product_id` + `ProductConfig`；`__post_init__` 把旧 flower_dir/font_source/layout_defaults 合成「产品0=生日花卡」，load/save 双向 + `active_product()`。✅ `tests/test_product_config_migration.py`(4)，真实配置只读迁移验证通过。
- [x] **Step 5（绿）** 全量 **317 passed, 0 failed**（含本轮 23 新测试；先前已知 red 也已消失）。birth-flower 库零配置可用、旧配置零感知迁移、金标/批量字节不变。ruff clean。**全程未碰 `ui_app.py`。**

**Task 1 完成（2026-06-14）。** 下一步 Task 2（UI，要改 `ui_app.py`）需先与改 UI 的另一条对话协调：让其先提交干净基线，再开独立分支接 Phase 2。

### Task 2：生产参数随图层 + 人工确认字段重构（Phase 2，UI）
**Files:** 改 `ui_app.py`；改/加 `tests/test_ui_app.py`。**只动 `ui_app.py` + 其测试，后端不用再改**（Phase 1/3 已铺好，接口缝已做成一行调用）。

#### 🔌 后端接线契约（给接手 Phase 2 的 UI 对话，照此调用即可，勿重造）
后端能力已落地并测好（Phase 1/3，全量 332 passed）。Phase 2 = 把下面 6 个缝接进 `ui_app.py`：

1. **启动 / 切产品 → 建库集合**
   ```python
   from config_store import load_config, active_product
   from order_catalog import LibraryBundle
   config = load_config(); product = active_product(config)          # 旧配置已零感知迁移出 product
   bundle = LibraryBundle.from_dirs(product.image_library_dirs, product.font_library_dirs)
   prod_defaults = product.defaults    # EngravingLayout：flower_*/text_*/text_size，作产品级生产默认
   ```
2. **人工确认「素材库 / 素材」选择器**（取代月份+花朵）
   - 素材库下拉候选 = `bundle.image_libraries`（显示 `lib.name`，值 `lib.id`）。
   - 选中库 `lib` → 素材下拉候选 = `lib.entries`（显示 `e.name`，可搜索；值 `e.key`；也可用 `lib.catalog().items`）。
   - 月份只作展示标签：`e.tags.get("month")`（不再是独立必填字段）。字体库/字体同理用 `bundle.font_libraries`。
3. **添加素材为图层（一行，工厂已支持新字段）**
   ```python
   from models import add_image_layer, add_text_layer
   add_image_layer(doc, entry.path, name=entry.name, x=.., y=.., width=.., height=..,
                   library_id=lib.id, material_key=entry.key, production=override_or_None)
   add_text_layer(doc, text, font_path=font_entry.path,
                  font_library_id=font_lib.id, font_key=font_entry.key, production=override_or_None)
   ```
4. **属性面板「生产参数随图层」**
   - 读：`layer.production`（`ProductionParams | None`）。展示**有效值** = `production.resolve_chain(prod_for_slot, lib.defaults, entry.defaults, layer.production)`（低→高优先级）。
   - 写：`layer.production = ProductionParams(width=.., height=.., x=.., y=.., font_size=..)`（只填用户改的字段，其余留 None 自动回落）。
   - `prod_for_slot`：图像层 = `ProductionParams(x=prod_defaults.flower_x, y=.flower_y, width=.flower_width, height=.flower_height)`；文本层 = `ProductionParams(x=.text_x, y=.text_y, width=.text_width, height=.text_height, font_size=.text_size)`。（沿用现有 `layout_vars` 的 flower_*/text_* 作初值也可，额外 override 才进 `layer.production`。）
5. **解析结果落图层（material_key 直达）**
   ```python
   from parse_pipeline import parse_order_remark_auto
   result = parse_order_remark_auto(remark, ai_config=.., bundle=bundle)   # 传 bundle 才富化
   # result 已带 material_key/font_key/selected_flower_asset/selected_font_asset，且旧 month/flower/font 已回填
   if result.material_key:
       lib = next(l for l in bundle.image_libraries if l.id == result.material_library_id)
       entry = lib.by_key(result.material_key)            # → add_image_layer(...)
   ```
6. **设置窗口管理库**：读写 `product.image_library_dirs/font_library_dirs`（`ProductConfig` frozen → `dataclasses.replace` 出新 product 塞回 `config.products`，`save_config` 持久化）。保留旧「花朵目录/字体来源」作迁移兼容入口。

> **WYSIWYG 红线**：几何最终仍必须经 `desktop_export._apply_canvas_fit` 的 contain-fit，**勿旁路**（见 §5 / 记忆 flower-text-layout-unified）。`production` 只决定图层初值/override，不替代 fit 管线。
> **Phase 3 Step 4（ParseResult→Document）已并入本 Task 的第 5 缝。**
- [ ] **Step 1（红）** 测试：选中图层后属性面板显示该层生产参数并可写回 `layer.production`；人工确认面板出现「素材库/素材/字体库/字体」选择器（数据驱动自 `Product.manual_fields`），「月份」不再是独立必填字段。
- [ ] **Step 2** 属性面板：选中图层读 `layer.production`（按 §5 回落显示有效值），编辑写回。
- [ ] **Step 3** 人工确认字段：`month_var/flower_var` → 「素材库 + 素材」选择器（候选=产品 image 库 catalog，可搜索；month 作筛选 chip）；`font_var` → 「字体库 + 字体」。
- [ ] **Step 4** 「添加素材」：用 §5 链路 seed 新图层生产参数（取代只用全局 `layout_vars`）；写 `library_id/material_key`。
- [ ] **Step 5** 设置窗口：管理「当前产品」的素材库/字体库列表（增删库文件夹）；保留旧「花朵目录/字体来源」作迁移兼容入口。
- [ ] **Step 6（绿）** 跑全量 + 手测：关 App 重开，选图层调参数、加不同库素材、导一单核 ezdxf 实体类型不变。

### Task 3：订单解析对接（Phase 3）
**实现策略（演进兼容，与原计划的偏差，已落地）：** 为零风险不破 `test_gpt_parser`/`test_parse_pipeline`/批量金标，**不改 `gpt_parser.py`、`local_order_parser.py`、`orders.py`**，而是新增 `order_catalog.py` 复用 gpt_parser 的 HTTP 辅助；`parse_pipeline` 只加可选 `bundle` 参数（不传则行为不变）。`ui_app.py` 的消费侧接线（原 Step 4）**挪到 Phase 2**（避免碰 UI 线）。
**Files（实际）:** 改 `models.py`(ParseResult+4字段)、`parse_pipeline.py`(可选 bundle 富化)；新增 `order_catalog.py`、`tests/test_order_catalog.py`。
- [x] **Step 1（红）** 测试 `tests/test_order_catalog.py`(12)：catalog 注入 prompt、动态枚举进 schema、模型回 key ∉ catalog → 丢弃+warning、`material_key→asset` 富化、birth-flower 路径 month/flower 由 tags 回填、GPT 离线调用、pipeline 富化接线、幂等。
- [x] **Step 2** `ParseResult` 加 `material_library_id/material_key/font_library_id/font_key`；`order_catalog.build_order_remark_schema`（动态枚举=库真实 key+null）+ `build_catalog_system_prompt`（注入目录）+ `parse_catalog_payload`（校验+富化）+ `parse_order_remark_with_gpt_catalog`（OpenAI/DeepSeek，复用 gpt_parser 辅助）。**`gpt_parser.py` 原样未动。**
- [x] **Step 3** 不改本地解析器；`enrich_parse_result` 把任意来源结果落到素材：material_key 动态枚举校验 → 旧 month+flower 标签反查 → flower_name 模糊；字体 font_key→index 标签→font_design。旧 month 逻辑天然成兜底。`LibraryBundle` + `resolve_*` 承载。
- [ ] **Step 4（挪到 Phase 2）** `ui_app` ParseResult→Document 用 `material_key` 落图层、回填新字段——属 UI 改动，与 Phase 2 一起在协调后做。
- [x] **Step 5（绿）** 全量 **329 passed, 0 failed**（317+12）。离线 mock，无真实 key。ruff clean。**未碰 `ui_app.py`/`gpt_parser.py`/`orders.py`。**

**Task 3 后端完成（2026-06-14）。** 剩 Step 4（ui_app 接线）并入 Phase 2。`services/api/.../orders.py`（web/批量 pydantic schema）待 web/批量需要 material_key 时再对齐。

### Task 4（Phase 4，后期）：多产品 UI + 产品切换器
**Files:** `ui_app.py`、`config_store.py`、文档。
- [ ] 左侧产品切换器（每窗口=一个产品）；新增第二个产品 + 其库验证模型通用性；更新 `PROJECT_INDEX.md`/`CURRENT_TASKS.md`/`AGENTS.md`。

## 9. 风险与验证

- **回归（最高）**：金标/批量字节。验证 = 每 Task 跑全量 pytest + 导一单真实输出，ezdxf 核实体类型（R2018 + SPLINE/POLYLINE，无 LWPOLYLINE/TEXT/HATCH）。
- **WYSIWYG**：生产参数链路若旁路 `_apply_canvas_fit` 会破坏「预览==导出」。验证 = `tests/test_text_wysiwyg_consistency.py` + 桌面四路定位偏差 <0.05mm 复测。
- **配置迁移**：旧 `birth_flower_config.json` 必须零操作迁移。验证 = `test_config_store.py` 加迁移用例。
- **范围蔓延**：产品切换器、真实 GPT key、第二个产品库——**全部延后到 Phase 3/4**，本设计只保证模型留好接口。
- **致命坑**：改完 Python 必须完全关 App 重开；pytest 必须 CWD=仓库根；用 `.venv-win`（任何解释器会自动 re-exec）。

## 10. 待用户确认 / 开放项（实现前再对齐）

1. **「素材库」与「产品」的归属**：库是「挂在产品下」（产品决定可用库）还是「全局库池 + 产品引用子集」？本设计按**产品引用库目录列表**（更简单）。如需库共享/复用，再抽全局池。
2. **字体也走 catalog 解析**？本设计是（字体库同素材库模型）。若字体短期仍固定几款，可只做 image 库、字体 Phase 3 再泛化。
3. **per-素材默认生产参数**写在 `library.json` 还是产品模板？本设计：库清单为主、产品 `defaults` 兜底（§5 回落链）。
4. **`test_physical_size` 既有红**：不在本需求范围，独立处理（已挂 task，见 CURRENT_TASKS）。

---
*依据：只读探查 `models.py`/`asset_resolver.py`/`config_store.py`/`gpt_parser.py`/`local_order_parser.py`/`parse_pipeline.py` 与 `ui_app.py` 人工确认/生产参数/设置区。行号为当时快照，实现前以实际代码为准。*
