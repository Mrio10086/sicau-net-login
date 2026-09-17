<#
.SYNOPSIS
    安装川农校园网自动登录：装依赖 + 创建开机自启快捷方式。

.EXAMPLE
    .\install.ps1
    .\install.ps1 -NoAutostart
    .\install.ps1 -Remove
#>
[CmdletBinding()]
param(
    [switch]$NoAutostart,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$shortcutPath = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\川农校园网自动登录.lnk'

if ($Remove) {
    if (Test-Path -LiteralPath $shortcutPath) {
        Remove-Item -LiteralPath $shortcutPath -Force
        Write-Host "已删除开机自启快捷方式。" -ForegroundColor Yellow
    } else {
        Write-Host "本来就没有开机自启快捷方式。" -ForegroundColor Yellow
    }
    return
}

Write-Host "== 检查 Python ==" -ForegroundColor Cyan
$python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $python) { throw "没找到 python，请先安装 Python 3.10+ 并加入 PATH" }
Write-Host ("Python: " + (& python --version 2>&1))

Write-Host "`n== 安装依赖 ==" -ForegroundColor Cyan
& python -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw "依赖安装失败" }

Write-Host "`n== 跑一遍单元测试 ==" -ForegroundColor Cyan
& python -m pytest -q (Join-Path $projectRoot 'tests')
if ($LASTEXITCODE -ne 0) { Write-Warning "单元测试没全过，请先看看输出" }

if (-not $NoAutostart) {
    Write-Host "`n== 创建开机自启快捷方式 ==" -ForegroundColor Cyan
    $pythonw = Join-Path (Split-Path $python.Source -Parent) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $python.Source }
    $entry = Join-Path $projectRoot 'run_tray.pyw'

    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = '"' + $entry + '"'
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = '川农校园网自动登录'
    $shortcut.Save()
    Write-Host "已创建：$shortcutPath"
}

Write-Host "`n完成。现在可以：" -ForegroundColor Green
Write-Host "  python run_tray.pyw     # 启动托盘程序（首次会弹设置窗口）"
Write-Host "  python cli.py status    # 看当前认证状态"
