# Creates a "TI 2026 Predictor" shortcut on the Desktop (and optionally the
# Start Menu) pointing at run.bat.
#
#   powershell -ExecutionPolicy Bypass -File tools\create_shortcut.ps1
#
param(
    [switch]$StartMenu,
    [string]$Name = "TI 2026 Predictor"
)

$ErrorActionPreference = "Stop"

$root   = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "run.bat"
$icon   = Join-Path $root "assets\ti2026.ico"

if (-not (Test-Path $target)) { throw "Khong tim thay run.bat tai $target" }

if (-not (Test-Path $icon)) {
    Write-Host "Chua co icon, dang tao..."
    & python (Join-Path $root "tools\make_icon.py")
}

$shell = New-Object -ComObject WScript.Shell

function New-AppShortcut([string]$linkPath) {
    $sc = $shell.CreateShortcut($linkPath)
    $sc.TargetPath       = $target
    $sc.WorkingDirectory = $root
    $sc.Description      = "Du doan tran dau The International 2026 (chay local)"
    $sc.WindowStyle      = 1
    if (Test-Path $icon) { $sc.IconLocation = "$icon,0" }
    $sc.Save()
    Write-Host "Da tao: $linkPath"
}

$desktop = [Environment]::GetFolderPath("Desktop")
New-AppShortcut (Join-Path $desktop "$Name.lnk")

if ($StartMenu) {
    $programs = [Environment]::GetFolderPath("Programs")
    New-AppShortcut (Join-Path $programs "$Name.lnk")
}
