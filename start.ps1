# ROSClaw baslatma scripti (Windows)
# Su an icin: sadece Gateway + Web UI baslatir (ROS2/Gazebo henuz WSL2'de kurulu degil).
# WSL2 + ROS2 + rosbridge kurulduktan sonra bu script genisletilip
# rosbridge websocket baglantisi da otomatik kontrol edilebilir.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

chcp 65001 | Out-Null
$env:PYTHONUTF8 = "1"

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Sanal ortam bulunamadi. Once kurulumu tamamlayin." -ForegroundColor Red
    exit 1
}

Write-Host "ROSClaw Gateway baslatiliyor..." -ForegroundColor Cyan
Write-Host "Arayuz: http://localhost:8000" -ForegroundColor Cyan
Write-Host ""
Write-Host "NOT: ROS2/Gazebo henuz baglanmadi (WSL2 kurulumu bekliyor)." -ForegroundColor Yellow
Write-Host "     Agent yine de calisir: Qwen2.5-Coder ile kod uretir, guvenlik" -ForegroundColor Yellow
Write-Host "     kontrollerini yapar, ama fiziksel/ROS2 komutlari WSL2+rosbridge" -ForegroundColor Yellow
Write-Host "     baglaninca gercek etki yaratir." -ForegroundColor Yellow
Write-Host ""

& ".\.venv\Scripts\python.exe" -m gateway.api
