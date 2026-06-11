# Flower React/FastAPI 版操作教程

这份教程按现在能打开的 React/FastAPI 版来写。界面目前还是英文按钮，但下面会用中文把每一步讲清楚。

当前入口：

```text
http://127.0.0.1:5173/
```

后端健康检查：

```text
http://127.0.0.1:8765/health
```

## 1. 先说现在这个版本能做什么

现在这个版本是新的网页编辑器原型，不是旧的 Tkinter 桌面窗口。

它现在能做这些事：

1. 打开 React 图层编辑器。
2. 自动连接本地 FastAPI 后端。
3. 在画布里编辑示例图层的位置、缩放、旋转、透明度。
4. 选择文字图层后，从字体字形面板里替换某个字符。
5. 把当前画布导出成 SVG。
6. 把当前画布导出成 PNG。
7. 查看当前设计的 JSON 数据。

它现在还没有完整接上这些生产流程：

1. 还没有订单备注输入框。
2. 还没有前端里的订单解析按钮。
3. 还没有前端里的模板选择流程。
4. 前端目前没有 DXF 导出按钮；DXF 后端接口已经有，但当前页面没做入口。
5. `Save JSON` 只是把当前 JSON 刷新到页面文本框，不是保存到磁盘文件。

所以，现在的正确使用目标是：先验证 React/FastAPI 版能跑、能编辑图层、能导出 PNG/SVG。

## 2. 怎么打开软件

### 2.1 最简单的打开方式

如果我已经帮你启动好了，直接打开浏览器，访问：

```text
http://127.0.0.1:5173/
```

看到页面标题是 `Flower`，大标题是 `Layer editor`，就说明前端打开了。

页面右上角会显示后端状态：

```text
flower-api
ok
```

看到 `ok`，说明 React 已经连上 FastAPI 后端。

### 2.2 自己从命令行启动

打开 PowerShell，进入项目目录：

```powershell
cd C:\Users\Administrator\Documents\flower
```

启动前后端：

```powershell
npm run dev
```

这个命令会同时启动两个服务：

```text
React 前端: http://127.0.0.1:5173/
FastAPI 后端: http://127.0.0.1:8765/
```

命令行里看到类似下面内容，就说明正常：

```text
VITE ready
Local: http://127.0.0.1:5173/
Uvicorn running on http://127.0.0.1:8765
```

然后打开浏览器访问：

```text
http://127.0.0.1:5173/
```

### 2.3 如果提示 Python 或依赖有问题

这个项目现在推荐用 Windows 标准 Python 虚拟环境：

```powershell
.\.venv-win\Scripts\python.exe --version
```

正常应该能看到 Python 3.12。

如果依赖没装，执行：

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r requirements.txt
```

不要优先用旧的：

```powershell
.\.venv\bin\python.exe
```

旧 `.venv` 是 MSYS Python，装 `pydantic-core`、`ruff`、`numpy` 这类依赖容易失败。

### 2.4 怎么停止软件

如果你是在 PowerShell 里运行的：

```powershell
npm run dev
```

要停止，就在那个 PowerShell 窗口按：

```text
Ctrl + C
```

如果是后台运行，先查端口对应进程：

```powershell
netstat -ano | findstr ":5173"
netstat -ano | findstr ":8765"
```

然后用查到的 PID 停掉：

```powershell
taskkill /PID 进程号 /T /F
```

## 3. 打开后先看哪里

页面大概分四块：

1. 顶部：项目标题和后端状态。
2. 左边 `Layers`：图层列表。
3. 中间：画布。
4. 右边：属性、字形、导出、JSON。

第一次打开时，页面已经放了一个示例设计：

1. `Reference photo`：左边的参考图层。
2. `Birth flower`：右边的花朵 SVG 图层。
3. `Customer name`：底部的文字图层，默认文字是 `Avery`。

这个示例不是客户真实订单，只是用来验证编辑器功能。

## 4. 怎么确认后端正常

看页面右上角状态。

正常状态：

```text
flower-api
ok
```

如果显示 `backend checking`，等几秒。

如果显示 `Failed to fetch` 或其他错误，说明后端没连上。按这个顺序查：

1. PowerShell 里 `npm run dev` 是否还在运行。
2. 浏览器能不能打开 `http://127.0.0.1:8765/health`。
3. 端口 `8765` 有没有被别的软件占用。
4. 如果后端没启动，重新执行 `npm run dev`。

后端健康检查正常时，打开这个地址会看到：

```json
{"status":"ok","service":"flower-api","version":"0.1.0"}
```

## 5. 图层怎么选

左边 `Layers` 面板里会列出当前图层。

点某一行，就选中那个图层。

推荐操作习惯：

1. 要调文字，就点 `Customer name`。
2. 要调花朵，就点 `Birth flower`。
3. 要调参考图，就点 `Reference photo`。

选中后，中间画布会出现对应对象，右边 `Properties` 会显示它的参数。

## 6. 怎么在画布上拖动和缩放

当前画布基于 Fabric.js。

常用操作：

1. 鼠标点中图层。
2. 拖动图层，可以改变位置。
3. 拖动控制点，可以缩放。
4. 旋转控制点，可以旋转。

画布操作适合粗调。

如果要精确调数值，用右边 `Properties`。

## 7. 右边 Properties 怎么用

选中一个图层后，右边 `Properties` 会出现这些字段：

```text
x
y
scale
rotation
opacity
visible
locked
```

每个字段的意思：

1. `x`：图层左上角横向位置。数值越大，越往右。
2. `y`：图层左上角纵向位置。数值越大，越往下。
3. `scale`：缩放比例。`1` 是原始大小，`0.5` 是一半，`2` 是两倍。
4. `rotation`：旋转角度。正数顺时针，负数逆时针。
5. `opacity`：透明度。`1` 是完全不透明，`0` 是完全透明。
6. `visible`：是否显示。取消勾选后，这个图层隐藏。
7. `locked`：是否锁定。勾选后，图层不能正常被编辑移动。

推荐调法：

1. 大概位置用鼠标拖。
2. 精确位置用 `x/y`。
3. 大小用 `scale`。
4. 想让图层半透明，就调 `opacity`。
5. 不想误碰某个图层，就勾 `locked`。

## 8. 怎么改文字效果

当前页面没有直接的文字输入框。

示例文字是写在当前 JSON 文档里的 `Customer name` 图层中，默认是：

```text
Avery
```

当前界面能调文字图层的位置、大小、旋转、透明度，也能通过字形面板替换字符。

如果要改成别的客户名字，现在需要后续补一个文字编辑控件，或者临时改 JSON/源码。也就是说，当前 UI 还不是完整订单生产界面。

## 9. Glyphs 字形面板怎么用

只有选中文字图层时，`Glyphs` 面板才有用。

操作步骤：

1. 左边 `Layers` 点 `Customer name`。
2. 右边找到 `Glyphs`。
3. `font` 下拉里选择一个字体。
4. `char` 下拉里选择要替换的字符位置。
5. 用筛选按钮缩小范围：
   - `all`：全部字形。
   - `pua`：私用区字形，通常是花体尾巴、装饰字。
   - `mapped`：有 Unicode 映射的正常字形。
   - `unmapped`：没有 Unicode 映射的字形。
6. 在下面字形格子里点一个字形。
7. 点完后，画布里的文字会更新。

举例：

`Avery` 有 5 个字符：

```text
0: A
1: v
2: e
3: r
4: y
```

如果你想替换最后的 `y`，就在 `char` 里选：

```text
4: y
```

然后在字形格子里点想要的 `y` 变体。

注意：

1. 如果某个字形格子显示 `gid`，说明它可能没有可直接替换的字符，按钮会不可用。
2. 字形替换会写入当前文档的 `glyphOverrides`。
3. 替换后要点 `Save JSON`，右下角 JSON 才会刷新显示最新数据。

## 10. Export 导出怎么用

右边 `Export` 面板有这些选项：

```text
scale
transparent
SVG
PNG
```

### 10.1 导出 SVG

点：

```text
SVG
```

浏览器会下载一个 `.svg` 文件。

SVG 会尽量保留：

1. 图层顺序。
2. SVG 花朵矢量内容。
3. 文本节点。
4. 元数据。

默认下载位置一般是浏览器的 `Downloads` 下载目录，不一定是项目里的 `outputs` 文件夹。

### 10.2 导出 PNG

点：

```text
PNG
```

浏览器会下载一个 `.png` 文件。

PNG 是位图，适合发给客户预览。

### 10.3 scale 怎么设置

`scale` 控制 PNG 导出倍率。

常用值：

```text
1    原尺寸
2    两倍尺寸，更清晰
0.5  一半尺寸
```

如果只是自己测试，用 `1`。

如果要给客户看，建议用 `2`。

### 10.4 transparent 怎么设置

`transparent` 控制导出背景。

勾上：

```text
transparent
```

导出会尽量使用透明背景。

不勾：

导出会带画布背景色。

客户确认图一般不勾，生产叠加图可以考虑勾。

## 11. JSON 面板怎么用

右下角是 `JSON` 面板。

点：

```text
Save JSON
```

它会做两件事：

1. 校验当前图层文档是否合法。
2. 把最新文档 JSON 显示在下面的文本框里。

注意：

`Save JSON` 现在不等于保存到磁盘。它只是刷新页面里的 JSON 文本。

如果状态显示：

```text
valid
```

说明当前文档结构没问题。

如果显示一串错误，说明当前图层数据不合法，需要先修。

## 12. 当前版本推荐操作 SOP

按这个顺序做，最不容易乱：

1. 打开 PowerShell。
2. 进入项目目录：

```powershell
cd C:\Users\Administrator\Documents\flower
```

3. 启动软件：

```powershell
npm run dev
```

4. 打开浏览器：

```text
http://127.0.0.1:5173/
```

5. 看右上角是不是 `flower-api ok`。
6. 左边 `Layers` 选择要编辑的图层。
7. 中间画布拖动图层，做粗调。
8. 右边 `Properties` 用数值做精调。
9. 如果要替换字形，先选 `Customer name`，再用 `Glyphs`。
10. 点 `Save JSON`，确认 JSON 状态是 `valid`。
11. 在 `Export` 里设置 `scale` 和 `transparent`。
12. 点 `SVG` 或 `PNG` 下载文件。
13. 到浏览器下载目录检查成品。

## 13. 常见问题

### 13.1 页面打不开

先确认服务有没有启动：

```powershell
netstat -ano | findstr ":5173"
```

如果没有任何输出，说明前端没跑起来。重新执行：

```powershell
npm run dev
```

### 13.2 后端状态不是 ok

先打开：

```text
http://127.0.0.1:8765/health
```

如果打不开，说明后端没跑起来。

检查 PowerShell 里有没有 `Uvicorn running on http://127.0.0.1:8765`。

没有的话，重新执行：

```powershell
npm run dev
```

### 13.3 端口被占用

查占用端口的进程：

```powershell
netstat -ano | findstr ":5173"
netstat -ano | findstr ":8765"
```

停掉对应 PID：

```powershell
taskkill /PID 进程号 /T /F
```

再重新启动：

```powershell
npm run dev
```

### 13.4 字体列表为空

先确认后端能访问字体接口：

```text
http://127.0.0.1:8765/fonts
```

如果返回空，说明项目字体目录里没扫到字体。

当前后端会扫描这些位置：

```text
assets/fonts
BirthMonth flowers
Birthmonth_font.ttf
```

把 `.ttf` 或 `.otf` 字体放到这些位置后，刷新页面。

### 13.5 点 PNG 没反应

先看右边 `Export` 标题旁边的状态。

常见原因：

1. 浏览器拦截下载。
2. 当前文档 JSON 不合法。
3. 画布里有外部资源无法被浏览器加载。

处理顺序：

1. 点 `Save JSON`，看是否 `valid`。
2. 先试导出 `SVG`。
3. 再试 `PNG`。
4. 看浏览器地址栏或下载图标有没有拦截提示。

### 13.6 下载文件在哪里

当前 React 页面用浏览器下载。

一般在：

```text
C:\Users\Administrator\Downloads
```

不是项目的：

```text
C:\Users\Administrator\Documents\flower\outputs
```

除非后续改成后端保存文件，否则前端按钮下载默认走浏览器下载目录。

## 14. 给当前版本的真实判断

现在 React/FastAPI 版已经能跑起来，也能证明核心编辑链路可用。

但它还不是完整生产软件。最缺的是：

1. 订单备注输入和解析入口。
2. 模板选择和应用入口。
3. 文本内容编辑入口。
4. DXF 前端导出入口。
5. JSON 保存到磁盘的入口。

所以当前最适合做：

1. 前后端联调。
2. Fabric 图层编辑验证。
3. 字体和字形接口验证。
4. PNG/SVG 导出验证。

如果要进入真实接单生产，下一步应该优先补订单解析、模板套用、文本编辑和 DXF 按钮。
