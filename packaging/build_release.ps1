<#
.SYNOPSIS
  统一构建「生产工作台」绿色包：依赖 → 三端测试 gate → 扩展构建 → PyInstaller → 组装 zip。

.DESCRIPTION
  产物：release\工作台\（Workbench\app.exe + config + data + extension-dist + 文档）以及
        release\Workbench-v<版本>.zip。
  默认复用 flower 的 .venv-win 作为构建 venv（已含 flower 全集依赖），仅补装 sqlalchemy/alembic/pyinstaller。

.PARAMETER Venv           构建用 venv 目录（相对 flower 根），默认 .venv-win
.PARAMETER EzcadSrc       Ezcad2.7.6 源目录；缺省按 EZCAD_SRC 环境变量 → 同级 ..\Ezcad2.7.6
.PARAMETER SkipTests      跳过三端测试 gate（不建议正式出包时跳过）
.PARAMETER SkipExtension  跳过 Chrome 扩展构建（npm）
.PARAMETER Version        版本号（用于 zip 文件名），默认 0.1.0

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\build_release.ps1
#>
[CmdletBinding()]
param(
  [string]$Venv = ".venv-win",
  [string]$EzcadSrc = "",
  [switch]$SkipTests,
  [switch]$SkipExtension,
  [string]$Version = "0.1.0"
)

$ErrorActionPreference = "Stop"
$FlowerRoot = Split-Path -Parent $PSScriptRoot     # packaging 的父目录 = flower 仓根
Set-Location $FlowerRoot

# ---- 解析 Ezcad 源 -----------------------------------------------------------
if (-not $EzcadSrc) {
  if ($env:EZCAD_SRC) { $EzcadSrc = $env:EZCAD_SRC }
  else { $EzcadSrc = Join-Path (Split-Path -Parent $FlowerRoot) "Ezcad2.7.6" }
}
$EzcadSrc = (Resolve-Path $EzcadSrc -ErrorAction SilentlyContinue).Path
if (-not $EzcadSrc -or -not (Test-Path (Join-Path $EzcadSrc "ezcad_auto_layout"))) {
  throw "未找到 Ezcad 源（需含 ezcad_auto_layout\）。用 -EzcadSrc 指定，或设环境变量 EZCAD_SRC。"
}
$env:EZCAD_SRC = $EzcadSrc      # 供 Workbench.spec 读取
Write-Host "Ezcad 源: $EzcadSrc" -ForegroundColor Cyan

# ---- venv 与构建依赖 ---------------------------------------------------------
$py = Join-Path $FlowerRoot "$Venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "未找到构建 venv 的 python：$py（用 -Venv 指定）" }
Write-Host "构建 venv: $py" -ForegroundColor Cyan
Write-Host "补装构建依赖（sqlalchemy / alembic / pyinstaller）…" -ForegroundColor Cyan
& $py -m pip install -q --disable-pip-version-check "sqlalchemy>=2.0" "alembic>=1.13" "pyinstaller>=6.0"
if ($LASTEXITCODE -ne 0) { throw "构建依赖安装失败" }

# ---- Chrome 扩展构建 ---------------------------------------------------------
$extDist = Join-Path $FlowerRoot "automation\extension\dist"
if (-not $SkipExtension) {
  $npm = (Get-Command npm -ErrorAction SilentlyContinue)
  if ($npm) {
    Write-Host "构建 Chrome 扩展（npm run build）…" -ForegroundColor Cyan
    if (-not (Test-Path (Join-Path $FlowerRoot "automation\extension\node_modules"))) {
      & npm --prefix "automation\extension" install
      if ($LASTEXITCODE -ne 0) { throw "扩展依赖安装失败" }
    }
    & npm --prefix "automation\extension" run build
    if ($LASTEXITCODE -ne 0) { throw "扩展构建失败" }
  } else {
    Write-Host "未找到 npm，跳过扩展构建（用 -SkipExtension 显式跳过可消除本提示）。" -ForegroundColor Yellow
  }
}

# ---- 三端测试 gate -----------------------------------------------------------
if (-not $SkipTests) {
  Write-Host "== flower 测试 ==" -ForegroundColor Cyan
  $env:PYTHONPATH = ".;services\api"
  & $py -m pytest tests "services/api/tests" -q
  $code = $LASTEXITCODE
  Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
  if ($code -ne 0) { throw "flower 测试失败" }

  Write-Host "== inbox-service 测试 ==" -ForegroundColor Cyan
  Push-Location "automation\inbox-service"
  $env:PYTHONPATH = "."
  & $py -m pytest -q
  $code = $LASTEXITCODE
  Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
  Pop-Location
  if ($code -ne 0) { throw "inbox-service 测试失败" }

  Write-Host "== Ezcad 测试 ==" -ForegroundColor Cyan
  Push-Location $EzcadSrc
  & $py -m unittest discover -s tests -p "test_*.py"
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { throw "Ezcad 测试失败" }
} else {
  Write-Host "已跳过测试 gate（-SkipTests）。" -ForegroundColor Yellow
}

# ---- PyInstaller -------------------------------------------------------------
Write-Host "== PyInstaller 打包 ==" -ForegroundColor Cyan
# 先清旧产物：避免历史构建残留文件（如曾误纳的 inbox.db* PII 文件）留在 dist 里。
if (Test-Path "dist\Workbench") { Remove-Item -Recurse -Force "dist\Workbench" }
& $py -m PyInstaller --noconfirm --clean "packaging\Workbench.spec"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }
$bundle = Join-Path $FlowerRoot "dist\Workbench"
if (-not (Test-Path (Join-Path $bundle "app.exe"))) { throw "打包结束但未找到 app.exe：$bundle" }

# ---- 组装 release\工作台 -----------------------------------------------------
Write-Host "== 组装 release ==" -ForegroundColor Cyan
$rel = Join-Path $FlowerRoot "release\工作台"
if (Test-Path $rel) { Remove-Item -Recurse -Force $rel }
New-Item -ItemType Directory -Force $rel | Out-Null

Copy-Item -Recurse $bundle (Join-Path $rel "Workbench")

# Ezcad 在冻结态读 exe 同级 config\settings.json；flower 读 exe 同级 data\。
$cfgDir = Join-Path $rel "Workbench\config"
New-Item -ItemType Directory -Force $cfgDir | Out-Null
Copy-Item "packaging\templates\settings.json" (Join-Path $cfgDir "settings.json") -Force
$dataDir = Join-Path $rel "Workbench\data"
New-Item -ItemType Directory -Force $dataDir | Out-Null
Copy-Item "packaging\templates\birth_flower_config.json" (Join-Path $dataDir "birth_flower_config.json") -Force

if (Test-Path $extDist) {
  Copy-Item -Recurse $extDist (Join-Path $rel "extension-dist")
} else {
  Write-Host "（无扩展 dist，未随包带扩展。）" -ForegroundColor Yellow
}

if (Test-Path "packaging\docs") { Copy-Item -Recurse "packaging\docs\*" $rel }

$zip = Join-Path $FlowerRoot "release\Workbench-v$Version.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $rel -DestinationPath $zip
Write-Host ""
Write-Host "完成 ✅" -ForegroundColor Green
Write-Host "  绿色目录: $rel"
Write-Host "  绿色 zip : $zip"
Write-Host "  入口     : Workbench\app.exe（双击=总启动器）"
