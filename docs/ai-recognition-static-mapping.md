# flower · AI 识别静态映射规则（分析与对照）

> 用途：纯分析/展示，**不改任何代码**。把「订单备注/截图 → 结构化字段 → 素材/字体」整条识别链路里所有**静态（写死/规则）映射**集中列出并互相对照。
> 核对日期：2026-06-17。事实来源（全部已逐行读过）：
> `local_order_parser.py`、`services/api/app/domain/orders/parser.py`、`birth_flower_parser.py`、`asset_resolver.py`、`parse_pipeline.py`、`gpt_parser.py`、`order_catalog.py`，素材清单来自 `BirthMonth flowers/`。
>
> ⚠️ 本文只描述「规则现状」，含若干**真实不一致**（见 §9），不代表它们都正确。

---

## 0. 名词与三条解析路径

> ⚠️ **2026-06-18 起本地规则已在编排层（`parse_pipeline`）全局停用，统一走 AI**：`parse_orders_auto`（多订单，生产用）与 `_resolve_order_remark`（单订单）都只调 GPT；AI 失败直接抛错、AI 不完整返回低置信 + warnings，**不再回退本地**。下文 §2–§6 的本地规则（`parser.py` / `birth_flower_parser.py` / `local_order_parser.py`）保留为**存档 / 可恢复参考**——模块文件仍在、单测仍跑，但编排层不再调用（调用处已注释保留）。

识别原有三种实现，靠 `parse_pipeline` 编排（下面两条本地路径现已停用，仅存档）：

| 路径 | 实现 | 何时用 | 映射特点 |
|---|---|---|---|
| **本地规则**（无 AI） | `local_order_parser` → 优先 `parser.py`（web 规则），异常回退 `birth_flower_parser`（legacy） | 未勾选「AI 优先」时；或 AI 失败兜底 | 全部写死在代码里（月名/别名/月→花/字段标签） |
| **AI 简单版** | `gpt_parser`（OpenAI / DeepSeek） | 勾选「AI 优先」且未传素材库 bundle | 固定 schema：`month 1-12 / font 1-8 / flower 1-2` |
| **AI catalog 版** | `order_catalog`（注入素材库目录） | 勾选「AI 优先」且传了 bundle | **动态枚举**：`material_key/font_key` 只能选目录里出现过的 key |

> 还有一条 `screenshot_parser.py`（订单截图→视觉模型，UI 未接），复用上面同一套 schema，不单列。

### 0.1 链路总览（哪步用哪张表）

```
订单文本
  │
  ├─[字段标签切片]  parser.py FIELD_LABELS / legacy _ORDER_FIELD_LABELS   → §2
  │
  ├─[月份]          MONTH_ALIASES(英) / _MONTH_PHRASES(多语言) / 裸数字     → §3
  │
  ├─[花材]          月号 + FLOWERS_BY_MONTH / _BIRTH_FLOWER_NAMES(别名)     → §4
  │                 序号(1/2) ──地面真相──> asset_resolver.PREFERRED_FLOWER_ORDER → 实际 SVG
  │
  ├─[字体]          只认编号 → asset_resolver.BUSINESS_FONT_GROUPS          → §5
  │
  └─[刻字文字]      _FIELD_RE 提取 + 停止词 + personalization 类型判定       → §6

AI 路径额外：ORDER_REMARK_SCHEMA / catalog 动态枚举 schema（§7）+ enrich 落素材（§7.3）
最终：parse_pipeline 完整性判定 + 失败回退 + 置信度（§8）
```

---

## 1. 涉及文件与各自承载的映射

| 文件 | 角色 | 关键常量 / 函数 |
|---|---|---|
| `local_order_parser.py` | 本地解析入口（先 web 规则，失败回退 legacy） | `parse_order_remark_local()` (:61)、`_personalization_type()` (:143) |
| `services/api/app/domain/orders/parser.py` | **主本地规则**（web 规则） | `MONTH_NAMES`(:10)、`MONTH_ALIASES`(:25)、`FLOWERS_BY_MONTH`(:52)、`FIELD_LABELS`(:67) |
| `birth_flower_parser.py` | **legacy 兜底**（多语言） | `_MONTH_PHRASES`(:69)、`_BIRTH_FLOWER_NAMES`(:54)、`_ORDER_FIELD_LABELS`(:18)、`_MONTH_NUMBER_TO_SHORT`(:39)、`_classify_personalization()`(:353) |
| `asset_resolver.py` | **地面真相**：序号→真实文件、字体编号 | `PREFERRED_FLOWER_ORDER`(:25)、`MONTH_NAME_TO_NUMBER`(:10)、`DISPLAY_NAMES`(:40)、`BUSINESS_FONT_GROUPS`(:49) |
| `parse_pipeline.py` | 编排：走 AI / 本地、完整性、回退 | `parse_order_remark_auto()`(:17)、`_resolve_order_remark()`(:34)、`_is_complete()`(:109) |
| `gpt_parser.py` | AI 简单版 schema + prompt | `ORDER_REMARK_SCHEMA`(:18)、prompt(:72 / :263)、`parse_gpt_payload()`(:101) |
| `order_catalog.py` | AI catalog 版（动态枚举 + 落素材） | `build_catalog_system_prompt()`(:166)、`build_order_remark_schema()`(:150)、`parse_catalog_payload()`(:177)、`enrich_parse_result()`(:69) |

---

## 2. 字段标签映射（label → 规范字段）

切片逻辑：找到所有「标签 + `:`/`：`/`=`」位置，把两个标签之间的文本归到前一个标签。两套标签表并存。

### 2.1 主规则 `parser.py FIELD_LABELS`（:67）

| 规范字段 | 可识别标签（任意一个，大小写不敏感） |
|---|---|
| `birth_flower` | `choose your birth flower`、`birth flower`、`出生花` |
| `customer_name` | `customer name`、`name`、`personalization`、`personalisation`、`text`、`客户名字`、`客户姓名`、`姓名`、`名字`、`刻字` |
| `month` | `birth month`、`month`、`月份` |
| `flower` | `flower`、`花朵`、`花` |
| `font` | `font design`、`font preference`、`font`、`字体偏好`、`字体` |
| `notes` | `special notes`、`special requests`、`notes`、`remarks`、`remark`、`特殊备注`、`备注`、`要求` |

### 2.2 legacy `birth_flower_parser._ORDER_FIELD_LABELS`（:18）

| 规范字段 | 标签 |
|---|---|
| `birth_flower` | `Choose Your Birth Flower`、`Birth Flower` |
| `birth_month` | `Birth Month` |
| `font_design` | `Font Design`、`Font` |
| `personalization` | `Personalization`、`Personalisation`、`Gift Message`、`Message`、`Name` |

legacy 另有「裸字段」识别（无结构标签时）：
- 姓名 `_FIELD_RE`(:10)：`name | text | tên | ten | nama | personalization | personalisation | 姓名 | ชื่อ`
- 字体 `_FONT_LABELS`(:15)：`font | 字体 | ฟอนต์ | phông | phong`
- 花 `_FLOWER_LABELS`(:16)：`flower | 花 | ดอกไม้ | bunga`

---

## 3. 月份映射

### 3.1 月号 → 月名

| 月号 | `parser.py MONTH_NAMES`（全称） | `legacy _MONTH_NUMBER_TO_SHORT`（缩写） |
|---|---|---|
| 1–12 | January … December | Jan … Dec |

`asset_resolver.MONTH_NAME_TO_NUMBER`(:10) 反向：英文全称（文件名用）→ 月号。

### 3.2 文本别名 → 月号

| 来源 | 覆盖语言 | 说明 |
|---|---|---|
| **`parser.py MONTH_ALIASES`（:25）** | **仅英文**（jan/january … dec/december，含 sept） | 主路径用；中文/多语言**不认** |
| **`legacy _MONTH_PHRASES`（:69）** | 英文 + **中文（一月…十二月）** + 泰语 + 越南语（含无声调） + 印尼语 | 仅在回退到 legacy 时生效 |

裸数字月份的上下文要求（防止把 font/flower 编号误当月份）：
- `parser.py._parse_month`：`\b(1[0-2]|[1-9])\b`（要求词边界）。
- `legacy._extract_month`：必须带上下文 `month/月/เดือน/tháng/bulan` 或 `数字+月`（如 `5 月`）。

> ⚠️ 见 §9-④：因为主路径仅英文、且「1月」连写可能踩词边界问题，**中文月份实际依赖 legacy 兜底**。

---

## 4. 月份 → 花材 → 序号 → 实际 SVG（核心）

### 4.1 地面真相（实际渲染用的就是这张）

序号(1/2) 由 `asset_resolver.PREFERRED_FLOWER_ORDER`(:25) 决定，文件名来自 `BirthMonth flowers/`（实际 **24 个 SVG = 12 月 × 2**）。

| 月 | flower 1 | flower 2 | SVG 文件 1 | SVG 文件 2 |
|---|---|---|---|---|
| 1 | Snowdrop | Carnation | `SnowdropJanuary` | `CarnationJanuary` |
| 2 | Violet | Primrose | `VioletFebruary` | `PrimroseFebruary` |
| 3 | Daffodil | Cherry Blossom | `DaffodilMarch` | `CherryMarch` |
| 4 | Daisy | Sweetpea | `DaisyApril` | `SweetpeaApril` |
| 5 | Lily of the valley | Hawthorn | `LilyofthevalleyMay` | `HawthornMay` |
| 6 | Rose | Honeysuckle | `JuneRose` | `HoneysuckleJune` |
| 7 | Waterlily | Larkspur | `Waterlilyjuly` | `LarkspurJuly` |
| 8 | Poppy | Gladiolus | `PoppyAugust` | `GladiolusAugust` |
| 9 | Aster | Morning Glory | `AsterSeptember` | `MorningGlorySeptember` |
| 10 | Marigold | Cosmos | `MarigoldOctober` | `CosmosOctober` |
| 11 | Chrysanthemum | Peony | `ChrysanthemumNovember` | `PeonyNovember` |
| 12 | Holly | Narcissus | `HollyDecember` | `NarcissusDecember` |

显示名规范化 `asset_resolver.DISPLAY_NAMES`(:40)：`cherry→Cherry Blossom`、`lilyofthevalley→Lily of the valley`、`morningglory→Morning Glory`、`sweetpea→Sweetpea`、`waterlily→Waterlily`。

### 4.2 三套来源对照（哪个月谁是 1 号花）

| 月 | asset_resolver（真相） | legacy `_BIRTH_FLOWER_NAMES` | `parser.py FLOWERS_BY_MONTH` |
|---|---|---|---|
| 1 | 1=Snowdrop 2=Carnation | 1=snowdrop 2=carnation ✅ | **1=Carnation 2=Snowdrop ❌反序** |
| 2–12 | 见上表 | 与真相一致 ✅ | 与真相一致 ✅ |

> 即：**只有 1 月，`parser.py` 把 1/2 写反了**（详见 §9-①）。

### 4.3 花名别名 → 序号（legacy `_BIRTH_FLOWER_NAMES`，:54）

模糊匹配用，去掉非字母数字后做包含匹配，命中最长别名优先：

| 月 | flower 1 别名 | flower 2 别名 |
|---|---|---|
| 1 | snowdrop | carnation |
| 2 | violet | primrose |
| 3 | daffodil | cherry blossom / cherry |
| 4 | daisy | sweetpea / sweet pea |
| 5 | lily of the valley / lilyofthevalley | hawthorn |
| 6 | rose | honeysuckle / honey suckle |
| 7 | waterlily / water lily | larkspur |
| 8 | poppy | gladiolus |
| 9 | aster | morning glory / morningglory |
| 10 | marigold | cosmos |
| 11 | chrysanthemum | peony |
| 12 | holly | narcissus |

序号取值范围：**flower ∈ {1, 2}**。

---

## 5. 字体映射

### 5.1 编号 → 字体（地面真相 `asset_resolver.BUSINESS_FONT_GROUPS`，:49）

> 2026-06-18 订正：旧规则「同名两个文件按大小分常规/带字形版」已废弃。现每家族只保留 1 个有效字体文件，同一文件同时承载常规与带末尾装饰两档。

规则：`malovelyscript` 起始编号 1，`adorabella` 起始编号 3。**每个家族仅 1 个字体文件**，同一文件按「基准编号（常规）」与「基准+1（带末尾装饰）」各产出一个字体选项（`_ordered_font_paths`）。`has_ending_glyphs = 编号 ∈ {2,4}`。末尾装饰的具体形态由 `glyph_service` 决定、与字体文件无关：

| 编号 | 字体家族 | 含义 | 末尾装饰来源 | 实际文件 |
|---|---|---|---|---|
| 1 | Malovely Script | 常规 | 无 | `Malovely Script.ttf` |
| 2 | Malovely Script | 带末尾字形 | 字体内 PUA 合体字形（`glyph_rules` end_char_rules E068–E081）| `Malovely Script.ttf` |
| 3 | AdoraBella | 常规 | 无 | `AdoraBella.ttf` |
| 4 | AdoraBella | 带末尾爱心 | 独立实心爱心 SVG 矢量（`SYMBOL_HEART_FONTS`，跳过字体字形）| `AdoraBella.ttf` |

实际字体文件仅 2 个：`Malovely Script.ttf`、`AdoraBella.ttf`（旧 `.otf` 已删）→ 由这 2 个文件各分裂出常规/装饰两档，**真实编号 1–4**。

### 5.2 各路径允许的 font 编号范围（不一致）

| 来源 | 允许范围 | 备注 |
|---|---|---|
| `gpt_parser` `ORDER_REMARK_SCHEMA` / `ORDER_ITEM_SCHEMA` | **1–4** | AI schema：2026-06-18 由 1–8 收紧到 1–4（`_bounded_int` 同步），越界裁 `null` |
| `parser.py._parse_font` | 1–8 | 正则 `(?:font)?([1-8])`（本地解析仍留 5–8 预留位） |
| legacy 结构化 `_font_number_from_design` | 1–8 | `font\s*([1-8])`（同上，留预留位） |
| legacy 非结构化 `_extract_number_choice` | **1–4** | 超出报「font 只能是 1-4」 |
| 实际素材 | 1–4 | 2 个字体文件各分裂出常规/装饰两档 |

> 2026-06-18 起 **AI 路径已对齐实际素材（1–4）**；本地/legacy 的结构化解析仍接受 1–8（给"后期加字体"留位，写「font 7」会原样提取但在 `order_batch` 字体素材校验处落空）。
>
> 字体识别**主要靠编号**；前台字体字段（`ui_app._default_field_defs` field3）已补「字体名/外观 → 编号」语义（Malovely/AdoraBella、末尾字形/末尾爱心），AI 路径可据此把口语描述映射到编号，本地规则仍只认数字。

---

## 6. 刻字内容（text / personalization）

### 6.1 提取与停止

- 提取起点：`_FIELD_RE`（name/text/姓名/tên/nama/ชื่อ 等）之后的文本。
- 停止于：分隔符 `, ; ， ；` 换行；或撞上停止词 `_TEXT_STOP_TOKENS`（= 所有月份短语 + font/flower 标签 + month/เดือน/tháng/bulan 等）；或 `数字+月`。
- 数字归一化 `normalize_unicode_digits`(:185) / `_normalize_digits`：把全角、泰文、阿拉伯等 Unicode 十进制数字统一成 ASCII。

### 6.2 personalization 类型判定（两套阈值，不一致）

| 来源 | 判为 `message` 的条件 | 否则 |
|---|---|---|
| `local_order_parser._personalization_type`(:143) | 长度 > 32 **或** 含句末标点（`. ! ? ; 。 ！ ？ …`） | 非空→`name`，空→`unknown` |
| `legacy._classify_personalization`(:353) | 词数 ≥ 5 **或**（含句末标点且词数 ≥ 3） | 非空→`name`，空→`unknown` |

---

## 7. AI 输出 schema 与校验（静态约束）

### 7.1 简单版 `gpt_parser.ORDER_REMARK_SCHEMA`（:18）

```jsonc
{
  "text":       "string",                 // 姓名或要雕刻文字
  "month":      "integer 1-12 | null",
  "font":       "integer 1-8 | null",
  "flower":     "integer 1-2 | null",     // 同月份第几个花朵素材
  "warnings":   "string[]",               // 中文提示
  "confidence": "number 0-1"
}
// 全部字段 required；strict json_schema
```
system prompt（OpenAI :72 / DeepSeek :263）：「你是 Birth Flower 订单备注解析器…缺失或不确定时填 null 并写中文 warnings」。
输出校验 `parse_gpt_payload`(:101)：`_bounded_int` 把越界值裁成 `null`（month 1-12 / font 1-8 / flower 1-2）。

模型默认值：`DEFAULT_MODEL = gpt-5-nano`、`DEFAULT_DEEPSEEK_MODEL = deepseek-v4-flash`、`max_output_tokens = 1200`；gpt-5/o1/o3/o4 加 `reasoning.effort = minimal`。

### 7.2 catalog 版动态枚举 `order_catalog.build_order_remark_schema`（:150）

```jsonc
{
  "text":         "string",
  "material_key": "enum(目录里的 key) | null",   // 不再是 month/flower 数字
  "font_key":     "enum(目录里的 key) | null",
  "warnings":     "string[]",
  "confidence":   "number 0-1"
}
```
- system prompt 注入「素材库目录 JSON」（`build_prompt_catalog`:142：每库 `{id,name,kind,items:[{key,name,aliases,tags}]}`）。
- `parse_catalog_payload`(:177)：模型若返回目录里没有的 key → **丢弃并记 warning**（防臆造）。
- 优点：新增素材只改 `library.json`/加文件，**本地零硬编码**。

### 7.3 落素材优先级 `enrich_parse_result`（:69，两条 AI/本地结果都会过）

| 目标 | 优先级（命中即停） |
|---|---|
| 素材 | ① `material_key`（库内校验）→ ② `month + flower` 标签反查 → ③ `flower_name` 模糊 |
| 字体 | ① `font_key`（库内校验）→ ② `font` 编号标签 → ③ `font_design` 模糊 |

命中不了不臆造；key 非法只记 warning。幂等（重复富化结果不变）。

---

## 8. 完整性判定 / 失败回退 / 置信度

### 8.1 编排 `_resolve_order_remark`（:34）

```
勾选「AI 优先」(enabled && prefer_ai)：
  GPT → 完整? → 是：返回（清空 warnings）
              → 否：本地 → 完整? → 是：返回
                                  → 否：合并失败（GPT+本地原因，confidence≤0.2）
未勾选：
  本地 → 完整? → 是：返回
              → 否：本地失败（confidence≤0.2）
```

### 8.2 「完整」定义 `_is_complete`（:109）

`text` 非空 **且** `month / font / flower` 三者均不为 `None`。（注意：catalog 版用 material_key/font_key，不直接含 month/flower 数字 —— 见 §9-⑤。）

### 8.3 置信度公式

| 函数 | 公式（要点） |
|---|---|
| `birth_flower_parser._calculate_confidence`(:554) | `命中字段数/4 − 0.05×warnings` |
| `._calculate_structured_parse_confidence`(:385) | 1.0 起扣：缺月/花 −0.35、缺字体 −0.25、缺刻字 −0.30、每 warning −0.05 |
| `._calculate_asset_confidence`(:405) | 1.0 起扣：有花名但无素材 −0.45、有字体但无字体素材 −0.35、每 warning −0.03 |
| `parse_pipeline._with_low_parse_confidence`(:84) | 失败时压到 ≤ 0.2 |

---

## 9. 发现的不一致 / 风险（如实记录，仅陈述、不修改）

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| ① | **1 月花 1/2 反序**：`parser.py` 写 `1=Carnation 2=Snowdrop`，真相/legacy 是 `1=Snowdrop 2=Carnation` | `parser.py FLOWERS_BY_MONTH`(:53) vs `asset_resolver`(:26)/`legacy`(:55) | 走主路径解析 1 月订单，「花 1/花 2」语义与实际素材相反 |
| ② | **font 范围不一致**：非结构化 legacy 限 1–4，其余 1–8，实际只有 4 个字体 | §5.2 | 订单写「font 5–8」在不同路径下表现不同（裁 null / 报错 / 接受但无素材） |
| ③ | **personalization 类型阈值两套不同** | `local_order_parser`(:143) vs `legacy`(:353) | 同一段文字可能一处判 name 一处判 message |
| ④ | **中文/多语言月份只在 legacy 兜底**：主路径 `parser.py` 仅英文+裸数字；「1月」连写还可能踩词边界 | `MONTH_ALIASES`(:25) vs `_MONTH_PHRASES`(:69) | 中文订单的月份识别实际走「主规则失败→回退 legacy」路径，链路较脆 |
| ⑤ | **两套 AI schema 并行**：简单版给 month/flower 数字，catalog 版给 key；`_is_complete` 按 month/flower 判完整 | §7.1 vs §7.2 | catalog 版结果若不回填 month/flower，完整性判定口径需注意 |
| ⑥ | **花名拼写差异影响模糊匹配**：`Sweet Pea` vs `Sweetpea`、`Lily of the Valley` vs `Lily of the valley`（`parser.py` vs `DISPLAY_NAMES`） | `parser.py`(:56,57) vs `asset_resolver DISPLAY_NAMES`(:42,44) | 跨表按名字反查时可能漏配（已靠 `_compact` 去符号缓解，但大小写/分词仍有差） |
| ⑦ | **素材数量**：实际 24 个 SVG（12×2），记忆/旧文档曾写「27 个」 | `BirthMonth flowers/` | 统计口径以实际目录为准 |

---

## 10. 一句话结论

- **本地规则**：写死在 `parser.py`（主，英文）+ `birth_flower_parser`（兜底，多语言）+ `asset_resolver`（序号/字体编号的地面真相）。
- **发给 API 的规则**：`gpt_parser`（固定 month/font/flower schema）+ `order_catalog`（注入素材库目录做动态枚举）。
- **真相锚点**：花序号→文件、字体编号 一律以 `asset_resolver` 为准；解析层（尤其 `parser.py` 的 1 月）存在 §9 所列不一致。
