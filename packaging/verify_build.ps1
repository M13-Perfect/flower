<#
.SYNOPSIS
  「生产工作台」构建后验证：泄密/臃肿复查 + 字体随包 + 冻结态四角色 check + serve /healthz。

.DESCRIPTION
  在 build_release.ps1 出包后跑，确认绿色包干净可用。任一 [FAIL] 都不该把包发出去。
  退出码：全过=0，有未过项=1。

.PARAMETER BundleDir  app.exe 所在目录，默认 <flower>\dist\Workbench
.PARAMETER Port       serve 探活用的临时端口，默认 8779（避开生产 8770）

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File packaging\verify_build.ps1
#>
[CmdletBinding()]
param(
  [string]$BundleDir = "",
  [int]$Port = 8779
)

$ErrorActionPreference = "Stop"
$FlowerRoot = Split-Path -Parent $PSScriptRoot
if (-not $BundleDir) { $BundleDir = Join-Path $FlowerRoot "dist\Workbench" }
$exe = Join-Path $BundleDir "app.exe"
$internal = Join-Path $BundleDir "_internal\srcflower"
$fail = 0

function Check([string]$name, [bool]$ok) {
  if ($ok) { Write-Host ("  [PASS] " + $name) -ForegroundColor Green }
  else { Write-Host ("  [FAIL] " + $name) -ForegroundColor Red; $script:fail++ }
}

Write-Host "== 1) 产物存在 ==" -ForegroundColor Cyan
if (-not (Test-Path $exe)) { throw "未找到 app.exe：$exe（先跑 packaging\build_release.ps1）" }
Check "app.exe 存在" $true

Write-Host "== 2) 泄密 / 臃肿复查 ==" -ForegroundColor Cyan
$ibx = Join-Path $internal "automation\inbox-service"
$pii = (Get-ChildItem $ibx -Recurse -Filter "inbox.db*" -ErrorAction SilentlyContinue | Measure-Object).Count
$bak = (Get-ChildItem $internal -Recurse -Filter "*.bak*" -ErrorAction SilentlyContinue | Measure-Object).Count
Check "无 inbox.db*（真实订单 PII）" ($pii -eq 0)
Check "无 *.bak*（备份 PII）" ($bak -eq 0)
Check "无 inbox .venv 误纳" (-not (Test-Path (Join-Path $ibx ".venv")))
Check "inbox app 仍在" (Test-Path (Join-Path $ibx "app\factory.py"))

Write-Host "== 3) 字体 / 花材随包 ==" -ForegroundColor Cyan
Check "Birthmonth_font.ttf 随包" (Test-Path (Join-Path $internal "Birthmonth_font.ttf"))
Check "BirthMonth flowers 随包"  (Test-Path (Join-Path $internal "BirthMonth flowers"))

Write-Host "== 4) 冻结态四角色 check（exit 0 = 导入路径成立）==" -ForegroundColor Cyan
foreach ($r in 'flower', 'ezcad', 'serve') {
  $p = Start-Process $exe -ArgumentList "check", $r -PassThru -Wait -WindowStyle Hidden
  Check ("check " + $r) ($p.ExitCode -eq 0)
}

Write-Host "== 5) serve /healthz（临时端口 + 临时数据）==" -ForegroundColor Cyan
$tmp = Join-Path $env:TEMP ("wb_verify_" + $Port)
$env:FLOWER_INBOX_PORT = "$Port"
$env:FLOWER_INBOX_DB = Join-Path $tmp "inbox.db"
$env:FLOWER_INBOX_DIR = Join-Path $tmp "outputs\inbox"
$env:FLOWER_REPORTS_DIR = Join-Path $tmp "outputs\reports"
$env:FLOWER_BATCHES_DIR = Join-Path $tmp "outputs\inbox-batches"
$sp = Start-Process $exe -ArgumentList "serve" -PassThru -WindowStyle Hidden
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 500
  try { $resp = Invoke-WebRequest ("http://127.0.0.1:" + $Port + "/healthz") -UseBasicParsing -TimeoutSec 2; if ($resp.StatusCode -eq 200) { $ok = $true; break } } catch {}
}
Stop-Process -Id $sp.Id -Force -ErrorAction SilentlyContinue
Check "serve /healthz 通" $ok

Write-Host ""
if ($fail -eq 0) {
  Write-Host "验证全部通过 ✅  可以发包：$BundleDir" -ForegroundColor Green
  exit 0
} else {
  Write-Host ("验证有 " + $fail + " 项未通过 ❌  请排查后再发包。") -ForegroundColor Red
  exit 1
}
