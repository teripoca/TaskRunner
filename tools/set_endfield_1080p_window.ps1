# 终末地 Unity 分辨率设置写入脚本
# 右键 → 使用 PowerShell 运行，或直接双击
# 运行完后再启动终末地就是 1920x1080 窗口模式

$ErrorActionPreference = "Continue"
$regPath = "HKCU:\Software\Hypergryph\Endfield"

if (-not (Test-Path $regPath)) {
    Write-Host "找不到终末地注册表键：$regPath"
    Write-Host "请确认游戏至少启动过一次。"
    timeout 10
    exit 1
}

$targetWidth = 1920
$targetHeight = 1080
$fullscreenMode = 3  # 0=独占全屏 1=全屏窗口 2=最大化窗口 3=窗口化

function Set-Dword {
    param($Name, $Value)
    try {
        Set-ItemProperty -Path $regPath -Name $Name -Value $Value -ErrorAction Stop
        Write-Host "  OK: $Name = $Value"
    } catch {
        Write-Host "  失败: $Name -> $Value"
    }
}

Write-Host "正在写入终末地注册表设置..."
Write-Host "目标分辨率: ${targetWidth}x${targetHeight}"
Write-Host "窗口模式: 窗口化`n"

# ========== Unity PlayerPrefs 实际启动分辨率 ==========
Set-Dword "Screenmanager Resolution Width_h182942802" $targetWidth
Set-Dword "Screenmanager Resolution Height_h2627697771" $targetHeight
Set-Dword "Screenmanager Resolution Width Default_h680557497" $targetWidth
Set-Dword "Screenmanager Resolution Height Default_h1380706816" $targetHeight
Set-Dword "Screenmanager Resolution Window Width_h2524650974" $targetWidth
Set-Dword "Screenmanager Resolution Window Height_h1684712807" $targetHeight
Set-Dword "Screenmanager Fullscreen mode_h3630240806" $fullscreenMode
Set-Dword "Screenmanager Fullscreen mode Default_h401710285" $fullscreenMode
Set-Dword "Screenmanager Resolution Use Native_h1405027254" 0
Set-Dword "Screenmanager Resolution Use Native Default_h1405981789" 0

# ========== 游戏设置 UI 里显示的分辨率 ==========
Set-Dword "video_resolution_width_h583690364" $targetWidth
Set-Dword "video_resolution_height_h2517654917" $targetHeight
Set-Dword "video_full_screen_h1998742411" 0

Write-Host "`n已完成。下一次启动终末地就会是 ${targetWidth}x${targetHeight} 窗口模式。"
timeout 5
