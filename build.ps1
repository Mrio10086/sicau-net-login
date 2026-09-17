<#
.SYNOPSIS
    把「川农校园网自动登录」打包成单个 exe。

.EXAMPLE
    .\build.ps1                 # 单文件 exe（默认）
    .\build.ps1 -OneDir         # 文件夹版，启动更快
    .\build.ps1 -Clean          # 打包前先清掉 build/dist
    .\build.ps1 -NoTest         # 跳过单元测试
#>
[CmdletBinding()]
param(
    [switch]$OneDir,
    [switch]$Clean,
    [switch]$NoTest,
    [switch]$SkipCli,
    [string]$Name = 'sicau-net-login'
)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

Push-Location $projectRoot
try {
    Write-Host '== 检查 Python ==' -ForegroundColor Cyan
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw '没找到 python，请先安装 Python 3.10+ 并加入 PATH'
    }
    Write-Host ("Python: " + (& python --version 2>&1))

    Write-Host "`n== 安装依赖（含 pyinstaller）==" -ForegroundColor Cyan
    & python -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller
    if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }

    if (-not $NoTest) {
        Write-Host "`n== 跑单元测试 ==" -ForegroundColor Cyan
        & python -m pytest -q tests
        if ($LASTEXITCODE -ne 0) { throw '单元测试没通过，先修好再打包' }
    }

    Write-Host "`n== 生成图标 ==" -ForegroundColor Cyan
    & python tools\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw '图标生成失败' }

    if ($Clean) {
        foreach ($dir in @('build', 'dist')) {
            if (Test-Path -LiteralPath $dir) {
                Remove-Item -LiteralPath $dir -Recurse -Force
            }
        }
    }

    Write-Host "`n== 开始打包（第一次会慢一些）==" -ForegroundColor Cyan
    # spec 会生成在 build/ 下，所以这些路径必须给绝对路径
    $iconPath = Join-Path $projectRoot 'packaging\app.ico'
    $srcPath = Join-Path $projectRoot 'src'
    $mode = if ($OneDir) { '--onedir' } else { '--onefile' }
    $common = @(
        '-m', 'PyInstaller',
        '--noconfirm',
        '--clean',
        '--icon', $iconPath,
        '--paths', $srcPath,
        '--hidden-import', 'pystray._win32',
        '--exclude-module', 'matplotlib',
        '--exclude-module', 'numpy',
        '--exclude-module', 'pandas',
        '--exclude-module', 'PyQt5',
        '--exclude-module', 'PySide6',
        '--distpath', 'dist',
        '--workpath', 'build',
        '--specpath', 'build'
    )

    Write-Host "`n-- 托盘版（无控制台窗口）--" -ForegroundColor Cyan
    & python @common '--windowed' $mode '--name' $Name (Join-Path $projectRoot 'build_entry.py')
    if ($LASTEXITCODE -ne 0) { throw '打包托盘版失败' }

    if (-not $SkipCli) {
        Write-Host "`n-- 命令行版 --" -ForegroundColor Cyan
        & python @common '--console' '--onefile' '--name' "$Name-cli" (Join-Path $projectRoot 'cli_entry.py')
        if ($LASTEXITCODE -ne 0) { throw '打包命令行版失败' }
    }

    Write-Host "`n== 完成 ==" -ForegroundColor Green
    $targets = @()
    $targets += if ($OneDir) { Join-Path $projectRoot "dist\$Name\$Name.exe" } else { Join-Path $projectRoot "dist\$Name.exe" }
    if (-not $SkipCli) { $targets += Join-Path $projectRoot "dist\$Name-cli.exe" }
    foreach ($target in $targets) {
        if (Test-Path -LiteralPath $target) {
            $size = [math]::Round((Get-Item -LiteralPath $target).Length / 1MB, 1)
            Write-Host "产物：$target （$size MB）"
        } else {
            Write-Warning "没找到 $target"
        }
    }
    Write-Host "`n直接双击即可运行，托盘图标会出现在右下角。"
    Write-Host '首次运行请在设置里填学号密码；开机自启可在设置窗口里勾选。'
}
finally {
    Pop-Location
}


