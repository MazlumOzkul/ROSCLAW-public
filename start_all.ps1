# ROSClaw - Tum sistemi baslatir (Windows oturum acilisinda otomatik calisir).
# Sirasi: Ollama hazir olmasini bekle -> WSL2 Gazebo -> rosbridge -> Gateway.
# Gorev Zamanlayicisi (Task Scheduler) tarafindan "ROSClaw-AutoStart" adiyla
# oturum acilisinda tetiklenir. Elle de calistirilabilir.

Set-Location $PSScriptRoot
chcp 65001 | Out-Null
$env:PYTHONUTF8 = "1"

function Wait-ForOllama {
    Write-Host "Ollama'nin hazir olmasi bekleniyor..." -ForegroundColor Cyan
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 2
            Write-Host "Ollama hazir." -ForegroundColor Green
            return $true
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Host "UYARI: Ollama 60 saniyede yanit vermedi, yine de devam ediliyor." -ForegroundColor Yellow
    return $false
}

function Wait-ForWSL {
    Write-Host "WSL2'nin hazir olmasi bekleniyor..." -ForegroundColor Cyan
    for ($i = 0; $i -lt 20; $i++) {
        $result = wsl -d Ubuntu-24.04 -- echo ok 2>$null
        if ($result -eq "ok") {
            Write-Host "WSL2 hazir." -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds 2
    }
    Write-Host "UYARI: WSL2 hazir olmadi, yine de devam ediliyor." -ForegroundColor Yellow
    return $false
}

Wait-ForOllama | Out-Null
Wait-ForWSL | Out-Null

Write-Host "Gazebo + TurtleBot3 baslatiliyor (ayri pencere)..." -ForegroundColor Cyan
Start-Process wsl.exe -ArgumentList "-d","Ubuntu-24.04","--","bash","-c","source /opt/ros/jazzy/setup.bash && export TURTLEBOT3_MODEL=burger && ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py"

Start-Sleep -Seconds 15

Write-Host "rosbridge_websocket baslatiliyor (ayri pencere)..." -ForegroundColor Cyan
Start-Process wsl.exe -ArgumentList "-d","Ubuntu-24.04","--","bash","-c","source /opt/ros/jazzy/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml"

Start-Sleep -Seconds 6

Write-Host "ROSClaw Gateway baslatiliyor: http://localhost:8000" -ForegroundColor Green
& ".\.venv\Scripts\python.exe" -m gateway.api
