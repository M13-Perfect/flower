# 对齐标准 DXF 素材 — 完整实现规格

> 参照样件:`C:\Users\Administrator\Desktop\3~4076779088.dxf`(订单 4076779088,"Nathalie")
> 由 Claude 解剖 + 渲染确认(2026-06-13)。用户已确认两项产品决策(见下)。

## 标准件的事实(对齐目标)

- **版本**:DXF R2018(AC1032),**保留 `$INSUNITS=4`(mm)**。
- **轮廓**:`SPLINE` 实体(平滑曲线,样件 59 条),非扁平折线。
- **填充**:`HATCH`(SOLID,样件 12 个,`solid_fill=1`/`pattern=SOLID`)表示实心区域。
- **图层**:单层(样件名"图层1")+ `0`/`Defpoints`,颜色 7。
- **范围**:`$EXTMIN/$EXTMAX` 是哨兵值 ±1e20(ezdxf 通病,**无关紧要**,CAD 自行重算)。
- **编组**:无 block / 无 INSERT,散开实体。
- **布局美学**:花在**左上**、名字在**右下**(斜向流动)。

## 关键结论(纠正既往判断)

- EzCad2 "选中改不动" 的根因是**实体类型**(LWPOLYLINE 不可编辑),**不是版本新旧**——
  样件 R2018(比原来的 R2010 更新)却可编辑,因为用 SPLINE。
  ⇒ 可改回 R2018 找回 mm 单位,同时用 SPLINE/HATCH(均可编辑)。
- 范围哨兵值确认无关(样件也是 ±1e20)。

## 用户确认的产品决策

1. **文字填充**:实心(HATCH SOLID)与空心(SPLINE 轮廓)**两种都要保留**,
   并在**前端留切换入口**。默认实心(跟标准件)。
2. **布局**:花左上 / 名字右下 是**所有订单的统一模板**。设为模板默认布局,前端可微调。

## 实现计划(分阶段,每阶段用渲染对比 + 结构核验)

### 阶段 1 — DXF 格式核心:R2018 + SPLINE 轮廓
- `_write_dxf`:版本改 `R2018`,保留 `$INSUNITS=INSUNITS[units]`(mm)。
- 几何管线改为构建 `ezdxf.path.Path` 对象(贝塞尔 `curve4_to`/`curve3_to`/`line_to`),
  不再扁平化成点;用 `ezdxf.path.render_splines_and_polylines` 输出 SPLINE。
- 改动 `_parse_path_shapes` / `_glyph_shapes`:产出 Path(经 matrix 变换)而非 PathShape 点集。
- 保留 Y 翻转(画布 Y 向下→DXF Y 向上)。
- 单层 + 颜色 7。

### 阶段 2 — HATCH 填充 + 文字实/空心开关
- 区分描边路径(→SPLINE)与填充路径/字形(→可选 HATCH SOLID)。
- 字形默认 HATCH SOLID(实心);开关切到空心时输出 SPLINE 轮廓。
- 用 `ezdxf.path.render_hatches`(带孔洞/counter 处理,如 a/e 的内圈)。
- 配置项 `exportSettings.text.fill: "solid"|"outline"`,经模板/前端控制。

### 阶段 3 — 布局对齐(花左上 / 名字右下)
- 模板引擎默认布局改为:花占左上、名字占右下(斜向),对应 85×90 画布。
- 配合既有决策:画布为准 + 前端可精确调坐标(布局设置对话框)。
- 花朵 meet 等比填充到槽位边界(此前 Workstream 2,墨迹包围盒)。

### 阶段 4 — 前端开关 + UI
- `布局设置` 或导出区加"文字填充:实心/空心"开关,写入模板 exportSettings,
  批量与按钮路径共用同一数据源。

## 验证标准(每阶段)
- 用 `asset-qa\render_dxf.py` 渲染我的输出,肉眼对比标准件风格。
- 结构核验:版本 R2018、实体类型(SPLINE/HATCH)、INSUNITS=4、单层、Y 朝向。
- `asset-qa\check_assets.py` 体检通过(R12 分支已放宽,需再加 R2018+SPLINE 适配)。
- 最终判官:用户把管线 DXF 导入 EzCad2,确认可编辑 + 实/空心 + 布局 + 朝向。

## 参照工具(均在 `C:\Users\Administrator\Documents\asset-qa\`,仓库外)
- `analyze_reference.py` — 解剖任意 DXF 结构
- `render_dxf.py` — ezdxf 原生 SVG 后端渲染(无需 matplotlib)→ 再 cairosvg 转 PNG
- `check_assets.py` — 产物体检(SVG/DXF/PNG/报告)
- `make_r12.py` / `dxf_editability.py` — 早期排查脚本
