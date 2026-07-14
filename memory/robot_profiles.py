"""
ROSClaw Robot Profilleri

Farkli robotlara (simulasyon, TurtleBot3, Unitree G1 veya rosbridge acan
herhangi bir ROS2 robotu) baglanti bilgilerini kalici olarak saklar - tipki
bir WiFi ag listesi gibi. Her profil kendi guvenlik limitlerini, izinli
topic listesini ve hareket komut tarzini tasir; robot degistirmek kod
degil, profil degistirmek anlamina gelir.
"""

from __future__ import annotations
import json, time, uuid, os
from pathlib import Path


# Bilinen robot tipleri icin hazir varsayilan ayarlar. Kullanici yeni bir
# profil eklerken bu tiplerden birini secerse alanlar otomatik doldurulur,
# istedigi gibi degistirebilir. "generic" bilinmeyen/ozel robotlar icindir.
ROBOT_PRESETS = {
    "gazebo_sim": {
        "label": "Gazebo Simulation (TurtleBot3)",
        "velocity_limits": {"max_linear": 0.5, "max_angular": 1.0},
        "topic_allowlist": {
            "publish": ["/cmd_vel", "/gripper/command", "/arm/joint_trajectory", "/head/cmd"],
            "subscribe": ["/scan", "/odom", "/camera/image_raw", "/imu", "/battery_state"],
        },
        "movement_style": "twist_stamped",
        "notes": "",
    },
    "turtlebot3_real": {
        "label": "TurtleBot3 (real hardware)",
        "velocity_limits": {"max_linear": 0.22, "max_angular": 2.5},
        "topic_allowlist": {
            "publish": ["/cmd_vel"],
            "subscribe": ["/scan", "/odom", "/imu", "/battery_state"],
        },
        "movement_style": "twist_stamped",
        "notes": "",
    },
    "unitree_g1": {
        "label": "Unitree G1 (humanoid)",
        "velocity_limits": {"max_linear": 0.3, "max_angular": 0.6},
        "topic_allowlist": {
            "publish": ["/api/sport/request"],
            "subscribe": ["/sportmodestate", "/lowstate", "/wirelesscontroller"],
        },
        "movement_style": "unitree_sport",
        "notes": "LOW-LEVEL /lowcmd must NEVER be added to the allowlist - "
                 "direct per-motor control carries a fall risk, only the "
                 "high-level /api/sport/request should be used.",
    },
    "generic": {
        "label": "Generic ROS2 Robot (configure manually)",
        "velocity_limits": {"max_linear": 0.2, "max_angular": 0.5},
        "topic_allowlist": {"publish": [], "subscribe": []},
        "movement_style": "unknown",
        "notes": "Discover this robot's topics/message format with "
                 "ros2_list_topics(), then update the allowlist accordingly.",
    },
}


class RobotProfileStore:
    """Kaydedilmis robot baglanti profillerini yonetir (WiFi ag listesi gibi)."""

    def __init__(self, path: str = "config/robot_profiles.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.profiles: list[dict] = []
        self.active_id: str | None = None
        self._load()
        if not self.profiles:
            self._seed_default()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.profiles = data.get("profiles", [])
            self.active_id = data.get("active_id")

    def _save(self):
        self.path.write_text(json.dumps(
            {"profiles": self.profiles, "active_id": self.active_id},
            indent=2, ensure_ascii=False), encoding="utf-8")

    def _seed_default(self):
        """Ilk calistirmada .env'deki ROS2_HOST/PORT ile uyumlu varsayilan profili ekle."""
        preset = ROBOT_PRESETS["gazebo_sim"]
        self.add({
            "name": "Gazebo Simulation",
            "host": os.environ.get("ROS2_HOST", "localhost"),
            "port": int(os.environ.get("ROS2_PORT", "9090")),
            "robot_type": "gazebo_sim",
            "velocity_limits": preset["velocity_limits"],
            "topic_allowlist": preset["topic_allowlist"],
            "movement_style": preset["movement_style"],
            "notes": preset["notes"],
        }, set_active=True)

    def list_profiles(self) -> list:
        return self.profiles

    def get(self, profile_id: str) -> dict | None:
        for p in self.profiles:
            if p["id"] == profile_id:
                return p
        return None

    def add(self, profile: dict, set_active: bool = False) -> str:
        profile_id = profile.get("id") or uuid.uuid4().hex[:12]
        profile["id"] = profile_id
        profile.setdefault("created_at", time.time())
        profile.setdefault("last_connected_at", None)
        self.profiles.append(profile)
        if set_active:
            self.active_id = profile_id
        self._save()
        return profile_id

    def delete(self, profile_id: str) -> bool:
        before = len(self.profiles)
        self.profiles = [p for p in self.profiles if p["id"] != profile_id]
        if self.active_id == profile_id:
            self.active_id = None
        self._save()
        return len(self.profiles) < before

    def set_active(self, profile_id: str):
        profile = self.get(profile_id)
        if profile:
            profile["last_connected_at"] = time.time()
            self.active_id = profile_id
            self._save()

    def get_active(self) -> dict | None:
        return self.get(self.active_id) if self.active_id else None


if __name__ == "__main__":
    import os as _os
    _os.chdir(Path(__file__).parent.parent)
    store = RobotProfileStore(path="logs/test_robot_profiles.json")
    print("Profiller:", store.list_profiles())
    print("Aktif:", store.get_active())
    Path("logs/test_robot_profiles.json").unlink(missing_ok=True)
    print("\n[OK] RobotProfileStore hazir")
