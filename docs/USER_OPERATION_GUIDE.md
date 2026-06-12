# Flower 操作教程

这份文档按当前已经跑通的 React/FastAPI 版来写。

软件入口：

```text
http://127.0.0.1:5173/
```

后端检查地址：

```text
http://127.0.0.1:8765/health
```

当前版本不是旧的 Tkinter 窗口，而是浏览器里的图层编辑器。主流程是：填订单备注，解析订单，套出生花模板，手动调图层，最后导出或保存 PNG/SVG/DXF。

## 1. 先确认软件能不能打开

### 1.1 我已经启动好时

直接打开浏览器，访问：

```text
http://127.0.0.1:5173/
```

页面顶部会看到：

```text
Flower
Layer editor
```

右上角正常状态是：

```text
flower-api
ok
```

看到 `ok` 就说明前端已经连上本地后端。

### 1.2 自己从 PowerShell 启动

打开 PowerShell，进入项目目录：

```powershell
cd C:\Users\Administrator\Documents\flower
```

启动软件：

```powershell
npm run dev
```

这个命令会同时启动两个服务：

```text
前端页面: http://127.0.0.1:5173/
后端 API: http://127.0.0.1:8765/
```

命令行里看到类似这些内容，就是启动成功：

```text
VITE ready
Local: http://127.0.0.1:5173/
Uvicorn running on http://127.0.0.1:8765
```

然后用浏览器打开：

```text
http://127.0.0.1:5173/
```

### 1.3 检查后端

浏览器打开：

```text
http://127.0.0.1:8765/health
```

正常会返回：

```json
{"status":"ok","service":"flower-api","version":"0.1.0"}
```

如果这个地址打不开，页面右上角通常也不会显示 `ok`。

### 1.4 停止软件

如果你是在 PowerShell 里运行的：

```powershell
npm run dev
```

要停止就在那个 PowerShell 窗口按：

```text
Ctrl + C
```

如果端口被占用，先查：

```powershell
netstat -ano | findstr ":5173"
netstat -ano | findstr ":8765"
```

再按查到的 PID 停掉：

```powershell
taskkill /PID 进程号 /T /F
```

## 2. 页面每一块是干什么的

页面大概分三列：

左边是订单和图层：

```text
Order
Layers
```

中间是画布：

```text
Canvas
```

右边是属性、文字、字形、导出和 JSON：

```text
Properties
Text
Glyphs
Export
JSON
```

第一次打开时会显示一个示例设计，默认有 3 个图层：

```text
Customer name
Birth flower
Reference photo
```

示例只是用来测试编辑器，不是真实订单。

## 3. 填订单并套模板

左上角 `Order` 面板里有两个输入框：

```text
id
note
```

`id` 是订单号，可以不填，但建议填，方便后面查文件。

`note` 是订单备注。当前解析器需要备注里把关键字段写清楚，不要让软件猜。

推荐格式：

```text
Customer name: Lily
Birth month: March
Flower: Cherry Blossom
Font: Font 2
Notes: demo only
```

也可以写成一行，只要字段名和冒号清楚：

```text
Customer name: Lily Birth month: March Flower: Cherry Blossom Font: Font 2 Notes: demo only
```

填好后点击：

```text
Parse + apply
```

正常情况下，软件会做三件事：

1. 解析客户名字、月份、花、字体。
2. 自动套用 `birth-flower-card` 模板。
3. 生成新的图层文档。

解析成功后，`Order` 面板下面会显示：

```text
name
flower
font
```

例如：

```text
name   Lily
flower Cherry Blossom
font   Font 2
```

同时左边 `Layers` 会变成类似：

```text
Customer name
Birth flower - Cherry Blossom
```

## 4. 订单备注怎么写更稳

当前解析器是确定性规则，不是随便猜。它认这些字段：

```text
Customer name
Name
Personalization
Text
客户名字
客户姓名
姓名
刻字
```

月份可以写：

```text
Birth month: March
Month: 3
月份: 3
```

花可以写：

```text
Flower: Cherry Blossom
Flower: 2
花朵: Cherry Blossom
```

字体可以写：

```text
Font: Font 2
Font: 2
字体: 2
```

最稳的做法：每个字段单独一行。

如果缺字段，页面会报类似订单解析失败。这不是 bug，是防止把客户订单猜错。

## 5. 选择和调整图层

左边 `Layers` 里点图层名称，就会选中这个图层。

常用选择：

```text
Customer name                 调文字
Birth flower - Cherry Blossom 调花
Reference photo               调参考图
```

选中后，中间画布会出现控制框。

画布里可以直接操作：

1. 鼠标拖动：移动图层。
2. 拖四角控制点：缩放图层。
3. 拖旋转控制点：旋转图层。

画布适合粗调。

精确调整用右边 `Properties`。

## 6. Properties 属性怎么用

选中一个图层后，右边 `Properties` 会显示：

```text
x
y
scale
rotation
opacity
visible
locked
```

含义：

```text
x        横向位置，数值越大越往右
y        纵向位置，数值越大越往下
scale    缩放比例，1 是原大小，0.5 是一半，2 是两倍
rotation 旋转角度，正数顺时针，负数逆时针
opacity  透明度，1 是不透明，0 是全透明
visible  是否显示
locked   是否锁定
```

推荐用法：

1. 先用鼠标拖到大概位置。
2. 再用 `x/y` 精确对齐。
3. 大小用 `scale` 微调。
4. 不想误碰某个图层，就勾 `locked`。
5. 只是临时隐藏，不要删图层，取消 `visible` 就行。

## 7. 修改文字

先在左边 `Layers` 里选：

```text
Customer name
```

右边会出现 `Text` 面板。

`content` 输入框就是当前文字内容。

例如把：

```text
Lily
```

改成：

```text
Sophia
```

画布会跟着更新。

`font` 下拉框可以选后端扫描到的字体。字体列表加载完成后，面板旁边会显示字体数量。

注意：如果没有选中文字图层，`Text` 面板会显示：

```text
No text layer selected.
```

这时先去左边点 `Customer name`。

## 8. 使用 Glyphs 字形面板

`Glyphs` 是给花体字、特殊尾巴、PUA 字形用的。

先选中文字图层：

```text
Customer name
```

再看右边 `Glyphs` 面板。

里面常见控件：

```text
font
char
all
pua
mapped
unmapped
```

`char` 是选择要替换哪个字符。

例如 `Lily` 有 4 个字符：

```text
0: L
1: i
2: l
3: y
```

如果要换最后的 `y`，就在 `char` 里选：

```text
3: y
```

再在下面字形格子里点想用的字形。

筛选按钮含义：

```text
all      全部字形
pua      私用区字形，常见于花体尾巴和装饰字符
mapped   有 Unicode 映射的正常字形
unmapped 没有 Unicode 映射的字形
```

字形替换后会写进当前 JSON 文档里的 `glyphOverrides`。

## 9. 保存 JSON

右下角 `JSON` 面板有：

```text
Save JSON
```

点击后会做两件事：

1. 校验当前图层文档结构。
2. 把最新 JSON 刷新到下面文本框。

状态是：

```text
valid
```

说明当前文档结构正常。

注意：`Save JSON` 只是刷新页面里的 JSON，不是保存到磁盘文件。

真正保存到项目 `outputs` 文件夹，要用 `Save all`。

## 10. 导出 SVG、PNG、DXF

右边 `Export` 面板有：

```text
scale
transparent
SVG
DXF
PNG
Save all
```

### 10.1 scale

`scale` 主要影响 PNG 导出倍率。

常用值：

```text
1    原尺寸
2    两倍尺寸，更清晰
0.5  一半尺寸
```

客户预览建议用 `1` 或 `2`。

### 10.2 transparent

`transparent` 控制导出背景。

勾上：导出尽量透明背景。

不勾：导出带画布背景色。

客户确认图一般不勾。后续要叠到别的图上时，可以考虑勾。

### 10.3 SVG

点击：

```text
SVG
```

浏览器会下载一个 `.svg` 文件。

SVG 适合保留矢量结构，后续继续处理也方便。

### 10.4 PNG

点击：

```text
PNG
```

浏览器会下载一个 `.png` 文件。

PNG 是位图，适合发客户预览。

### 10.5 DXF

点击：

```text
DXF
```

浏览器会下载一个 `.dxf` 文件。

DXF 主要给后续切割、雕刻、矢量生产流程用。

注意：DXF 对文字和复杂图形要求更严格。当前版本会调用后端 DXF 导出接口，如果图层里有不适合 DXF 的内容，页面会显示导出警告。

## 11. Save all 一键保存

如果你想把当前订单的所有结果都保存到项目目录，点：

```text
Save all
```

它会一次生成：

```text
order.json
design.svg
preview.png
design.dxf
```

保存位置在：

```text
C:\Users\Administrator\Documents\flower\outputs\订单名\
```

订单名优先用客户名字。

例如订单客户名是 `Lily`，保存后目录是：

```text
C:\Users\Administrator\Documents\flower\outputs\Lily\
```

里面会有：

```text
order.json
design.svg
preview.png
design.dxf
```

页面 `Export` 标题旁边显示：

```text
saved outputs/Lily
```

就说明保存完成。

## 12. 推荐完整操作流程

按这个顺序做，最不容易错：

1. PowerShell 进入项目：

```powershell
cd C:\Users\Administrator\Documents\flower
```

2. 启动软件：

```powershell
npm run dev
```

3. 浏览器打开：

```text
http://127.0.0.1:5173/
```

4. 看右上角是不是：

```text
flower-api
ok
```

5. 在 `Order -> id` 填订单号。

6. 在 `Order -> note` 填订单备注，例如：

```text
Customer name: Lily
Birth month: March
Flower: Cherry Blossom
Font: Font 2
Notes: demo only
```

7. 点击：

```text
Parse + apply
```

8. 看 `Order` 面板下面解析结果是否正确。

9. 左边 `Layers` 选择要改的图层。

10. 中间画布拖动粗调位置。

11. 右边 `Properties` 精调位置、大小、旋转、透明度。

12. 如果要改名字，选 `Customer name`，到 `Text -> content` 修改。

13. 如果要换花体尾巴或特殊字形，到 `Glyphs` 里选字符和字形。

14. 点 `Save JSON`，确认 JSON 状态是 `valid`。

15. 要单独下载文件，就点 `SVG`、`PNG` 或 `DXF`。

16. 要一次保存完整生产文件，就点 `Save all`。

17. 到 `outputs\客户名\` 检查结果文件。

## 13. 常见问题

### 13.1 页面打不开

先查前端端口：

```powershell
netstat -ano | findstr ":5173"
```

没有输出，说明前端没跑。重新执行：

```powershell
npm run dev
```

### 13.2 右上角不是 ok

打开：

```text
http://127.0.0.1:8765/health
```

如果打不开，说明后端没跑。

重新启动：

```powershell
npm run dev
```

### 13.3 Parse + apply 报错

优先检查订单备注是不是缺字段。

必须至少有：

```text
Customer name
Birth month
Flower
Font
```

不要只写：

```text
Lily March Cherry Blossom Font 2
```

这种太模糊。

要写成：

```text
Customer name: Lily
Birth month: March
Flower: Cherry Blossom
Font: Font 2
```

### 13.4 字体列表为空

打开：

```text
http://127.0.0.1:8765/fonts
```

如果 `fontCount` 是 0，说明后端没扫到字体。

当前项目里已有字体文件时，刷新页面一般会重新加载。如果你新放了字体，建议重启：

```powershell
npm run dev
```

### 13.5 点 PNG/SVG/DXF 后找不到文件

单独点 `PNG`、`SVG`、`DXF` 是浏览器下载。

一般在：

```text
C:\Users\Administrator\Downloads
```

不是项目里的 `outputs`。

如果想保存到项目目录，用：

```text
Save all
```

### 13.6 Save all 后文件在哪里

在：

```text
C:\Users\Administrator\Documents\flower\outputs\客户名\
```

例如：

```text
C:\Users\Administrator\Documents\flower\outputs\Lily\
```

### 13.7 图层拖不动

先检查右边 `Properties`：

```text
locked
```

如果勾上了，取消勾选。

再检查：

```text
visible
```

如果取消了，图层会隐藏。

### 13.8 画布里看不到花

可能原因：

1. 图层被隐藏。
2. 图层被拖到画布外。
3. 花朵素材没找到。

处理顺序：

1. 选中花朵图层。
2. 确认 `visible` 勾上。
3. 把 `x/y/scale` 调回合理范围。
4. 重新点一次 `Parse + apply` 套模板。

## 14. 当前版本的真实边界

当前 React/FastAPI 版已经跑通这些能力：

1. 打开浏览器编辑器。
2. 连接本地 FastAPI 后端。
3. 解析订单备注。
4. 套出生花模板。
5. 编辑图层位置、缩放、旋转、透明度、显隐、锁定。
6. 修改文字内容。
7. 选择字体和字形。
8. 导出 SVG、PNG、DXF。
9. `Save all` 保存完整输出到 `outputs`。

当前还不是最终生产级完整软件，主要限制：

1. 模板选择现在固定使用 `birth-flower-card`。
2. 订单解析要求字段清楚，不能靠模糊备注猜。
3. DXF 对复杂图形和文字仍要人工检查。
4. 浏览器下载文件和 `Save all` 保存文件是两套路径，别混用。

最低成本 SOP：平时生产优先用 `Parse + apply` 生成草稿，再人工检查图层，最后用 `Save all` 保存全套文件。
