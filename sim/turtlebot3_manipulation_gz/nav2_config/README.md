# Nav2 + SLAM harita dosyalari

Bu klasordeki dosyalar WSL2'nin Linux dosya sisteminde (`/root/rosclaw_sim/`)
uretildi ve dogrudan orada kullanildi - Windows tarafindaki bu kopya, GitHub'a
yuklenip yeni bir bilgisayarda tekrar WSL2'ye kopyalanabilmesi icin burada
tutuluyor.

- **`nav2_params.yaml`** - ozel Nav2 parametreleri. Iki kritik duzeltme icerir:
  - 5 node'da (`controller_server`, `behavior_server`, `velocity_smoother`,
    `collision_monitor`, `docking_server`) `enable_stamped_cmd_vel: true` -
    bunsuz robot Nav2'den "SUCCEEDED" alir ama hic hareket etmez (bkz.
    README.md "Cozulen kritik hata" bolumu).
  - `inflation_radius` kapida guvenli gecis icin dusuruldu.
- **`rosclaw_map_v2.yaml` + `rosclaw_map_v2.pgm`** - `slam_toolbox` ile
  cikarilmis, tum evi (salon+mutfak+yatak_odasi) kapsayan SLAM haritasi.

## Yeni bilgisayarda nasil kullanilir

```bash
# WSL2 icinde:
mkdir -p /root/rosclaw_sim
cp /mnt/c/ROSCLAW/sim/turtlebot3_manipulation_gz/nav2_config/*.yaml /root/rosclaw_sim/
cp /mnt/c/ROSCLAW/sim/turtlebot3_manipulation_gz/nav2_config/*.pgm /root/rosclaw_sim/
```

Sonra Nav2'yi bu dosyalarla baslat:
```bash
ros2 launch nav2_bringup bringup_launch.py use_sim_time:=true \
    map:=/root/rosclaw_sim/rosclaw_map_v2.yaml \
    params_file:=/root/rosclaw_sim/nav2_params.yaml
```
