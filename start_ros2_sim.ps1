# WSL2 icinde Gazebo + TurtleBot3 simulasyonunu ve rosbridge'i baslatir.
# Her ikisini de ayri pencerelerde acar (boylece kapatilmadan calismaya devam ederler).
# Kullanim: .\start_ros2_sim.ps1

Write-Host "Gazebo + TurtleBot3 baslatiliyor (ayri pencerede)..." -ForegroundColor Cyan
Start-Process wsl.exe -ArgumentList "-d","Ubuntu-24.04","--","bash","-c","source /opt/ros/jazzy/setup.bash && export TURTLEBOT3_MODEL=burger && ros2 launch turtlebot3_gazebo turtlebot3_world.launch.py"

Write-Host "10 saniye bekleniyor (Gazebo acilsin)..." -ForegroundColor Cyan
Start-Sleep -Seconds 10

Write-Host "rosbridge_websocket baslatiliyor (ayri pencerede)..." -ForegroundColor Cyan
Start-Process wsl.exe -ArgumentList "-d","Ubuntu-24.04","--","bash","-c","source /opt/ros/jazzy/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml"

Write-Host ""
Write-Host "Hazir olunca (birkac saniye icinde) http://localhost:9090 acik olmali." -ForegroundColor Green
Write-Host "Ardindan .\start.ps1 ile ROSClaw Gateway'i baslat: http://localhost:8000" -ForegroundColor Green
Write-Host "(Gateway acilista otomatik olarak rosbridge'e baglanmayi dener.)" -ForegroundColor Green
