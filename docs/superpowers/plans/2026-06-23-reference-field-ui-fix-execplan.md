# 引用字段系统 UI 修复 · Codex 执行计划（自包含）

> 日期：2026-06-23　状态：待执行（已评审，决策已拍板，见 §0.3）
> 适用：纯 Python 桌面端 `ui_app.py` + `prompt_references.py` + `config_store.py` + `gpt_parser.py`。
> 配套文档：同目录 `2026-06-23-reference-field-system.md`（设计基线）。本文是**执行交接锚点**，Codex 无需读审阅对话即可照做。
> 红线：**不换编辑器、不加新依赖、不改 `{{field:uuid}}` 存储格式、不改后端 resolver 语义、不扩大需求。**

---

## 0. 背景与结论（先读，防止跑偏）

### 0.1 真实生产链路
- 这是 **Tkinter / CustomTkinter 桌面 App**（`ui_app.py`），**不是 React/Web**。背景提示词编辑器是 `CTkTextbox` 纯文本框。
- Electron `apps/desktop` 是另一条未来 Web 轨道，**本次不碰**。
- 字段后端 `prompt_references.py` 已完成且有测试（`tests/test_reference_field_system.py`）；**bug 全在 `ui_app.py` 的 UI 集成层**，该层几乎无测试。

### 0.2 已确认根因（均有代码证据，对抗性核验通过）
- **R1（现象1：`{{field:UUID}}` 暴露给用户）**：背景提示词编辑器把存储层 token 串**直通显示**，缺少 token→`/名称` 显示层。`render_template_view` 只接在只读预览框，从不回写编辑器。
  - 证据：`ui_app.py` `_build_background_prompt_panel`(~3859 `box.insert("1.0", saved)`)、`_load_prompts_into_widgets`(~4140 `box.insert("1.0", prompt_template)`)、`_current_prompt_template_text`(~3868-3873 两支路都返回原始 token)、`render_template_view` 全文件仅 import + ~4156/4163（预览框 `generated_prompt_text`）。
- **R2（现象2：斜杠菜单读到旧名 `info3`）**：字段名输入框只在 `<Return>` 提交到 `product.reference_fields`，斜杠菜单读 `product.reference_fields`，未回车前读旧名。
  - 证据：`ui_app.py` 名称框 `CTkEntry(textvariable=field["name_var"])`(~3532)，仅 `name_entry.bind("<Return>", _save_reference_field_name)`(~3539-3543)，无 `<FocusOut>`、`name_var` 无 `trace_add`；斜杠候选 `active_reference_fields(product.reference_fields)`(~3887)。
- **R3（改名未回车被静默丢失，比 R2 更严重）**：`_reference_fields_from_field_defs`(~4055-4071) 从字段卡回写时**只同步 `prompt`/`field_type`，从不读 `name_var`**(~4064-4067)。任何 `_persist_prompts` 后下一次 `_render_fields` 用 `product.reference_fields` 重建 `name_var` → 用户没回车的名字被还原。
- **R4（现象2 序号）**：候选 `label = f"/#{seq} {name}"`、`insert = field_token(id)`(~3888/3891)，`_insert_slash_candidate` 只用 `insert`(~3985)。**`#序号` 永不入正文**；真正被插入的是 raw token（即 R1）。「`/#3` 写入引用」一说证伪。
- **R5（固定序号稳定/不复用）**：**已正确，无需改逻辑**。高水位 `field_seq_max`、软删保留序号、`field_seq_max` 单调不降。仅需清理 `_add_field`(~3582) 的过时误导注释。

### 0.3 决策（已拍板，Codex 直接按此执行；如需推翻请先问用户）
1. **重名策略**：维持现状（后端 `_ensure_unique_reference_name` 拒绝重名）。**不动后端校验。**
2. **`info3` 历史名**：不自动改名归一。靠显示层 + 用户重命名解决。**不写迁移。**
3. **chip 原子性**：MVP **不做**「光标跳过 / chip 内禁编辑」护栏。回读基于 tag、token 不丢，数据安全；chip 内部分编辑导致 `/名称` 视觉变花列为已知限制。
4. **`background_prompt` 被写成 token 串**：本轮**不清理**（与两 bug 无关），仅保留现状。
5. **DeepSeek/strip 预览口径**：作为可选收尾步骤 §3.4，主修复不依赖它。

### 0.4 执行顺序（每步独立可回滚）
1. **阶段 A = M1（现象2，零编辑器风险，先发）**：§3.1。
2. **阶段 B = M2/推荐（现象1 显示层）**：§3.2 + §3.3。
3. **阶段 C（可选收尾）**：§3.4。
> 每改一块：`python -m py_compile ui_app.py` + headless 渲染冒烟 + `pytest`。改完关 App 重开再手测。

---

## 1. 运行 / 测试 / 冒烟（致命坑）

- 用装了 `customtkinter` 的 **`.venv-win`** 跑：`.\.venv-win\Scripts\python.exe ui_app.py`。
- 测试基线：`PYTHONPATH=".;services\api" .\.venv-win\Scripts\python.exe -m pytest tests services/api/tests -q`。
- 渲染冒烟：建 `BirthFlowerApp(ctk.CTk())` → `root.update()` 无异常。
- **每次改完务必完全关掉 App 重开再测**（旧进程缓存旧代码）。
- 导出/批量字节稳定红线本次不涉及（只动提示词 UI 与字段名同步）。

---

## 2. 不变量（改动期间必须守住）

- 存储真相 = `product.prompt_template` 里的 `{{field:<uuid>}}` / `{{source:order_information}}` token 串，格式**不变**。
- `resolve_prompt_template` / `find_template_references` / `render_template_view` 语义**不变**（可被复用，不被改写）。
- `_current_prompt_template_text()` 永远返回 **canonical token 串**（这是 resolve/preview/persist 的统一入口）。
- 字段关联永远靠 `id`(uuid)，绝不靠 `reference_name` 或 `sequence_number`。

---

## 3. 按文件执行步骤

### 3.1 阶段 A — 现象2：名称实时同步 + 失焦持久化 + 回写补名（`ui_app.py`）

**A1. 名称框增补失焦提交。** 在 `_render_fields` 内名称框绑定处（当前 ~3539-3547，已有 `<Return>` 与 `<Escape>`）追加：
```python
name_entry.bind(
    "<FocusOut>",
    lambda _e, key=field["key"], var=field["name_var"], original=original_name:
    self._save_reference_field_name(key, var, original),
)
```
> 与 `inst_box` 的 `<FocusOut>` 落盘一致。用户要打 `/` 必先离开名称框 → 失焦即提交 → 菜单立即新鲜。

**A2. `_save_reference_field_name` 幂等 + 失焦不打扰。** 在函数入口（当前 ~3614）：
- 若 `var.get().strip() == original.strip()`：直接 `return`（名称未变不写盘、不重渲染、不弹窗）。
- 重名 / 空名异常分支（当前 `DuplicateReferenceNameError` / `ValueError`，~3623-3632）：保持 `var.set(original)` 回滚；把 `messagebox.showerror(...)` 降级为只 `self.status_var.set("字段名称未变更：<原因>")`（避免每次失焦弹模态）。`<Return>` 路径如需保留模态可加一个 `silent: bool=False` 形参区分（默认静默；Return 绑定传 `silent=False`）。
> 注意 `_save_reference_field_name` 末尾会 `_render_fields()`（~3643）全量重建字段卡——失焦后重建不会抢已转移走的焦点，但**手测必查**（§4 场景 6）。

**A3. 回写路径补 `reference_name` 同步（堵 R3 数据丢失）。** 在 `_reference_fields_from_field_defs`（~4055-4071）循环内，除现有 `prompt`/`field_type` 同步外，补名称同步：
```python
# 现有：update_reference_field_prompt(...) + replace(field_type=...)
name = item["name_var"].get() if "name_var" in item else str(item.get("name", ""))
if name.strip() and name.strip() != existing.reference_name:
    try:
        renamed = rename_reference_field(tuple(fields[-1:]) or (existing,), existing.id,
                                         name, scope_id=product.id)
        fields[-1] = renamed[0] if renamed else fields[-1]
    except ValueError:
        pass  # 空名/重名：保留旧名，不阻断 persist
```
> 实现细节由 Codex 按现有代码收敛：核心是「persist 时若 `name_var` 合法且变化，则经 `rename_reference_field` 校验后并入；校验失败保留旧名」。**不要**绕过 `rename_reference_field` 直接 `replace(reference_name=...)`（会跳过重名/空名校验）。

**A4. 清理过时注释。** `_add_field`（~3582）上方注释「编号基于现有字段数量+1（chip 实时按位置显示 infoN）…」与实现不符（实际高水位 `field_seq_max + 1` + 持久 `sequence_number`）。订正为：「序号由高水位 `field_seq_max + 1` 分配，删除不复用、不重排；chip 显示持久 `sequence_number`。」

**A1-A4 验收**：改名「info3」→「生日月份」**不回车**，点进背景框打 `/` → 菜单显「生日月份」；改名不回车再新增字段 → 名字不还原。

---

### 3.2 阶段 B-1 — 新增可测试分段渲染器（`prompt_references.py`）

新增函数（放在 `render_template_view` 附近，复用 `_TOKEN_RE`）：
```python
def iter_template_segments(template, *, fields, scope_id):
    """按原始顺序产出 (kind, ...) 段，供编辑器显示层与回读复用。
    yield 形如：
      ("text",   literal_str)
      ("field",  field_id, display_str)   # display = "/" + reference_name，无效→ "/无效字段(<id>)"
      ("source", source_key, display_str) # display = "/" + 标签
    """
```
- 用 `_TOKEN_RE.finditer` 切段，token 之间的纯文本作 `("text", ...)`。
- `field` 段：`field = _field_by_id(fields, value)`；`field is None or field.scope_id != scope_id` → `display = f"/无效字段({value})"`，否则 `"/" + field.reference_name`（与 `render_template_view` 对齐）。
- `source` 段：`"/" + SYSTEM_SOURCE_LABELS.get(value, f"未知数据源({value})")`。
- 可选：`render_template_view` 改为 `"".join(seg display)` 复用本函数（保持现有输出不变；有 `test_template_view_uses_friendly_names_and_rename_does_not_break_token` 护栏）。

**新增单测 `tests/test_template_segments.py`**：text/field/source 顺序、`/名称` 映射、无效 id→`/无效字段(...)`、`/订单信息`、重复引用、首尾 token、纯文本不被误判为引用。

---

### 3.3 阶段 B-2 — 编辑器 token↔`/名称` 显示层（`ui_app.py`）

**核心思路**：`CTkTextbox` 底层 `tk.Text`，token 作隐藏存储真相、`/名称` 作可见视图，用 tag 携带 `id`。

**B1. 新增 `_render_template_into_editor(self, template)`**：
```python
box = self.background_prompt_text
box.delete("1.0", "end")
product = active_product(self.config)
for seg in iter_template_segments(template, fields=product.reference_fields, scope_id=product.id):
    if seg[0] == "text":
        box.insert("insert", seg[1])
    else:                       # ("field"/"source", ref_id, display)
        kind, ref_id, display = seg
        start = box.index("insert")
        box.insert("insert", display)
        tag = ("ref::" if kind == "field" else "src::") + ref_id
        box._textbox.tag_add(tag, start, box.index("insert"))
        box._textbox.tag_add("chip", start, box.index("insert"))
# tag 样式（高亮成芯片观感），仅 _textbox 支持 tag_config：
box._textbox.tag_config("chip", foreground=APP_COLORS["accent"])  # 取既有色键
```
> 用 `box._textbox`（底层 tk.Text）做 `tag_add`/`tag_config`/`dump`——`CTkTextbox` 不一定转发这些方法。`tag` 名编码 id（`ref::<uuid>` / `src::<key>`），回读时解析。

**B2. 新增 `_template_text_from_editor(self) -> str`**（视图→canonical token）：
```python
box = self.background_prompt_text
if box is None:
    return ""
out, active_ref = [], None
for key, value, index in box._textbox.dump("1.0", "end-1c", tag=True, text=True):
    if key == "tagon" and (value.startswith("ref::") or value.startswith("src::")):
        if active_ref is None:                       # 进入一个 chip：emit 一次 token
            active_ref = value
            if value.startswith("ref::"):
                out.append(field_token(value[len("ref::"):]))
            else:
                out.append(system_token(value[len("src::"):]))
    elif key == "tagoff" and value == active_ref:
        active_ref = None
    elif key == "text" and active_ref is None:       # chip 外的纯文本原样保留
        out.append(value)
return "".join(out).strip()
```
> 规则：每个 tag 区段只 emit 一次 token（无论可见 `/名称` 是否被部分编辑）；chip 外文本原样。删掉整个 tag 区段 = 删除该引用（预期）。注意 `dump` 的 `chip` 辅助 tag 不要参与判断（只认 `ref::`/`src::` 前缀）。

**B3. `_current_prompt_template_text`（~3868）改取回读结果。** `box` 非空时：
```python
return self._template_text_from_editor()
```
替代原 `return box.get("1.0", "end-1c").strip()`。`box` 为 None 的回退分支保持不变。
> 这是中枢：改它之后 resolve(~4878)、preview(~4148)、persist(~4109) 全部自动拿到正确 token，无需各自改。

**B4. 编辑器加载改走渲染。**
- `_build_background_prompt_panel`（~3857-3859）：`if saved:` 分支把 `box.insert("1.0", saved)` 改为 `self._render_template_into_editor(saved)`。
- `_load_prompts_into_widgets`（~4137-4140）：`box.delete` + `box.insert` 改为 `self._render_template_into_editor(prompt_template)`（template 为空则跳过）。

**B5. 斜杠候选携带显示名与 id。** `_prompt_reference_candidates`（~3881）每个 candidate 增加键：
```python
{"label": f"/#{field.sequence_number} {field.reference_name}",  # 弹窗显示（含序号，仅展示）
 "display_name": "/" + field.reference_name,                     # 插入到编辑器的可见文本（无序号）
 "ref_kind": "field", "ref_id": field.id,
 "insert": field_token(field.id)}                                # 保留兼容/回读映射用
```
系统数据源项同理：`display_name="/订单信息"`、`ref_kind="source"`、`ref_id="order_information"`。

**B6. `_insert_slash_candidate`（~3979-3987）插入 chip 而非 raw token。**
```python
candidate = self._slash_candidates[...]
box.delete(self._slash_start_index, "insert")
start = box.index(self._slash_start_index)
box.insert(start, candidate["display_name"])
tag = ("ref::" if candidate["ref_kind"] == "field" else "src::") + candidate["ref_id"]
box._textbox.tag_add(tag, start, box.index("insert"))
box._textbox.tag_add("chip", start, box.index("insert"))
self._hide_slash_popup()
self._persist_prompts()
```
> 插入后**不要**全量重渲染编辑器（会乱光标）；tag 增量维护即可。`_persist_prompts` 走 B3 的回读，token 正确入盘。

**B1-B6 验收**：加载含 token 的模板 → 编辑器**不出现** `{{field:`，显示 `/名称`；斜杠插入「生日月份」→ 编辑器显 `/生日月份`、`_template_text_from_editor()` 含对应 `{{field:uuid}}`、不含 `#`/UUID 字面；保存重启后仍显 `/名称`。

---

### 3.4 阶段 C（可选）— 预览口径对齐 & 编辑器无效引用红标（`ui_app.py`）

- **C1（可选）**：`_show_generated_prompt`（~4142）`[final]` 段对齐实发：DeepSeek 补 `DEEPSEEK_ORDERS_JSON_SUFFIX`、统一 `.strip()`，使预览逐字等于实发。
- **C2（可选）**：`_render_template_into_editor` 对 `display` 以 `/无效字段(` 开头的段，`tag_config` 用 `APP_COLORS["warning"]` 标红，让编辑器内也能看到失效引用（删/停用字段后）。

---

## 4. 验收场景（手测，真窗口，关 App 重开）

1. 新建字段（#3，默认「字段3」）→ 改「生日月份」**不回车** → 点进背景框打 `/` → 菜单显「生日月份」；选后编辑器显 `/生日月份`，无 `#3`，无 UUID。
2. 新增字段改「字体」→ 立即 `/` → 菜单可选「字体」，无需刷新。
3. 选「生日月份」→ 保存 → **重启 App** → 编辑器显 `/生日月份`、预览 `[template]` 显 `/生日月份`、任何位置无 `{{field:UUID}}`。
4. 模板含 `/生日月份` → 解析 → 实发为该字段 `prompt` 全文，不发 `/生日月份`、不发 token。
5. 建 #1#2#3 → 删 #2 → 改 #3 名 → #3 仍是 #3；引用用名不含序号；新建为 #4。
6. **焦点时序专项**：从名称框直接点进背景框，验证 `<FocusOut>`→`_save_reference_field_name`→`_render_fields` 重建**不抢**背景框焦点（A2 风险点）。
7. **改名丢失回归**：改名不回车 → 增删另一字段 → 名字不还原（R3）。
8. **历史纯文本**：编辑器里手打 `/订单信息x`（无 tag）这类普通文本，保存重载后原样保留、不被误当引用。

---

## 5. 自动化测试清单

- `tests/test_template_segments.py`（新，§3.2）：分段器全路径。
- `tests/test_reference_field_system.py`（既有）：序号不复用 / 改名 token 不变 / resolver 原位展开 / 无效硬失败——回归确保后端未受影响。
- 编辑器回读映射：把 `_template_text_from_editor` 的核心映射逻辑抽成可测纯函数（或 headless 建窗后注入已知 token 串渲染→回读断言往返一致，含纯文本混排、`/订单信息`、未知文本不被误判）。
- headless 组件冒烟（沿用 `BirthFlowerApp(ctk.CTk())`）：加载 token 模板不显 `{{field:`、斜杠插入显 `/名称`+回读含 token、失焦改名后候选含新名、删 #2 后 chip 仍 #1/#3 新建 #4。
- 端到端黄金用例（设计文档例 16/17/18）：展开 == 例 17，预览 `[template]` 全 `/名称`、全程无 UUID。

---

## 6. 收尾（执行完务必做）

- 把背景 / 本次改动 / 已知问题折回 `AGENTS.md`（§14 约定）；`CURRENT_TASKS.md` 标注本计划状态。
- 已知遗留（如实记录，勿粉饰）：chip 原子性未做（§0.3.3）、`background_prompt` 仍存 token 串（§0.3.4）、`info3` 历史名靠用户手动改、C1/C2 是否落地。
- 真机手测 §4 全过一遍（拖放/焦点/链路无法纯自动化）。
