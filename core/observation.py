"""
ROSClaw Observation Normalizer - O katmani

Ham ROS2 sensor verisini modelin anlayabilecegi
temiz JSON/metin formatina cevirir.
"""

import json
import math
from typing import Any


class ObservationNormalizer:
    """
    ROSClaw sozlesmesinin O (Observation) katmani.
    Ham sensor -> temiz model girdisi.
    """

    def normalize(self, topic: str, raw_data: Any) -> dict:
        """Topic'e gore dogru normallestiriciyi sec."""
        if "/scan" in topic:
            return self._normalize_laser(raw_data)
        elif "/odom" in topic:
            return self._normalize_odom(raw_data)
        elif "/imu" in topic:
            return self._normalize_imu(raw_data)
        elif "/battery" in topic:
            return self._normalize_battery(raw_data)
        else:
            return {"raw": raw_data, "topic": topic}

    @staticmethod
    def _valid_range(r) -> bool:
        """Bir LaserScan olcumunun gecerli (engel tespit edilmis) sayilip
        sayilmayacagini kontrol eder. rosbridge, ROS'taki inf/-inf/NaN
        degerlerini (menzil disi/olcum yok anlamina gelir) JSON'a
        cevirirken null'a donusturuyor - bu yuzden Python tarafinda bunlar
        None olarak gelir. None kontrolu ONCE yapilmali, yoksa math.isinf/
        isnan None ile cagrildiginda TypeError firlatir (daha once bu hata
        disaridaki bare except'lerce sessizce yutulup front_distance'in
        gercek robot verisiyle SIK SIK None donmesine - yani LiDAR guard'in
        ve refleks katmaninin sessizce devre disi kalmasina - yol aciyordu)."""
        return (r is not None and not math.isinf(r) and not math.isnan(r)
                and r > 0)

    def _normalize_laser(self, data: dict) -> dict:
        """LaserScan -> anlasilir engel bilgisi."""
        ranges = data.get("ranges", [])
        if not ranges:
            return {"sensor": "laser", "status": "veri yok"}

        n = len(ranges)
        front = [r for r in ranges[int(n*0.4):int(n*0.6)] if self._valid_range(r)]
        left  = [r for r in ranges[int(n*0.6):int(n*0.9)] if self._valid_range(r)]
        right = [r for r in ranges[int(n*0.1):int(n*0.4)] if self._valid_range(r)]

        return {
            "sensor": "laser",
            "front_distance": round(min(front), 2) if front else 99.0,
            "left_distance":  round(min(left), 2)  if left  else 99.0,
            "right_distance": round(min(right), 2) if right else 99.0,
            "is_clear":       (min(front) > 0.5)   if front else True,
            "summary": self._laser_summary(front, left, right)
        }

    def _laser_summary(self, front, left, right) -> str:
        parts = []
        if front and min(front) < 0.5:
            parts.append(f"onde {min(front):.1f}m engel")
        if left and min(left) < 0.5:
            parts.append(f"solda {min(left):.1f}m engel")
        if right and min(right) < 0.5:
            parts.append(f"sagda {min(right):.1f}m engel")
        return ", ".join(parts) if parts else "yol acik"

    def _normalize_odom(self, data: dict) -> dict:
        """Odometry -> konum bilgisi."""
        pose = data.get("pose", {}).get("pose", {})
        pos = pose.get("position", {})
        return {
            "sensor": "odometry",
            "position": {
                "x": round(pos.get("x", 0), 3),
                "y": round(pos.get("y", 0), 3)
            },
            "summary": f"konum: x={pos.get('x',0):.2f}, y={pos.get('y',0):.2f}"
        }

    def _normalize_imu(self, data: dict) -> dict:
        """IMU -> denge bilgisi."""
        lin_acc = data.get("linear_acceleration", {})
        z_acc = lin_acc.get("z", 9.81)
        return {
            "sensor": "imu",
            "upright": abs(z_acc - 9.81) < 2.0,
            "summary": "dik" if abs(z_acc - 9.81) < 2.0 else "egik"
        }

    def _normalize_battery(self, data: dict) -> dict:
        """Batarya durumu."""
        percentage = data.get("percentage", -1) * 100
        return {
            "sensor": "battery",
            "level": round(percentage, 1),
            "summary": f"batarya: %{percentage:.0f}"
        }


if __name__ == "__main__":
    norm = ObservationNormalizer()
    test_scan = {
        "ranges": [0.3 if i < 50 else 5.0 for i in range(360)]
    }
    result = norm.normalize("/scan", test_scan)
    print("Laser normalizasyon testi:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n[OK] Observation Normalizer hazir")
