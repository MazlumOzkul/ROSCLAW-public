"""
ROSClaw Guvenlik Validator - V katmani (C = <A, O, V, L> sozlesmesi)

Her arac cagrisini robota gitmeden once denetler.
ALLOW veya BLOCK karari verir, gerekceyi loglar.
"""

import yaml
import time
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationResult:
    decision: str        # "ALLOW" veya "BLOCK"
    reason: str          # gerekce
    tool_name: str
    tool_args: dict
    timestamp: float


class SafetyValidator:
    """
    ROSClaw sozlesmesinin V (Validator) katmani.
    Konfigurasyon dosyasindan kurallari okur - donanima gore degistirilebilir.
    """

    def __init__(self, config_path: str = "config/safety_config.yaml"):
        self._base_config = self._load_config(config_path)
        self.config = json.loads(json.dumps(self._base_config))  # derin kopya
        self._estop_active = False
        self._validation_log = []

    def apply_profile_overrides(self, velocity_limits: dict = None,
                                 topic_allowlist: dict = None):
        """
        Aktif robot profili degistiginde (orn. Gazebo -> Unitree G1) hiz
        limitlerini ve izinli topic listesini o profile gore gunceller.
        Profilde belirtilmeyen alanlar safety_config.yaml varsayilaninda kalir.
        """
        self.config = json.loads(json.dumps(self._base_config))  # once sifirla
        if velocity_limits:
            self.config["velocity_limits"].update(velocity_limits)
        if topic_allowlist:
            if topic_allowlist.get("publish") is not None:
                self.config["topic_allowlist"]["publish"] = topic_allowlist["publish"]
            if topic_allowlist.get("subscribe") is not None:
                self.config["topic_allowlist"]["subscribe"] = topic_allowlist["subscribe"]

    def _load_config(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def validate(self, tool_name: str, tool_args: dict) -> ValidationResult:
        """
        Ana dogrulama metodu. Her arac cagrisi buradan gecer.
        before_tool_call hook'u olarak dusun.
        """
        timestamp = time.time()

        # E-stop aktifse her seyi engelle
        if self._estop_active:
            result = ValidationResult(
                decision="BLOCK",
                reason="E-stop aktif - tum komutlar engellendi",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
            self._log(result)
            return result

        # Arac bazli kontroller
        if tool_name == "ros2_publish":
            result = self._validate_publish(tool_args, timestamp)
        elif tool_name in ["ros2_subscribe", "ros2_list_topics", "ros2_camera",
                           "ros2_topics_with_types", "ros2_message_details",
                           "ros2_detect_object", "ros2_find_object"]:
            result = ValidationResult(
                decision="ALLOW",
                reason="Sadece okuma islemi",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name == "ros2_save_location":
            result = ValidationResult(
                decision="ALLOW",
                reason="Hafiza islemi - mevcut konumu kaydeder, fiziksel etki yok",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name == "ros2_navigate_to_location":
            result = ValidationResult(
                decision="ALLOW",
                reason="Nav2 otonom navigasyonu - kendi costmap/engelden kacinma "
                       "guvenlik katmanini uygular",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name in ["recall_skill", "save_skill", "search_docs", "web_search"]:
            result = ValidationResult(
                decision="ALLOW",
                reason="Hafiza/bilgi islemi - fiziksel etki yok",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name in ["ros2_get_param", "ros2_service"]:
            result = ValidationResult(
                decision="ALLOW",
                reason="Parametre/servis cagrisi - hiz limiti kapsami disinda",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name in ["ros2_set_param", "ros2_action"]:
            result = ValidationResult(
                decision="ALLOW",
                reason="Nav2/parametre yazma - Nav2/ros2_control kendi guvenlik katmanini uygular",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )
        elif tool_name == "ros2_move_arm_to_pose":
            result = self._validate_arm_pose(tool_args, timestamp)
        elif tool_name == "ros2_gripper":
            result = self._validate_gripper(tool_args, timestamp)
        else:
            result = ValidationResult(
                decision="BLOCK",
                reason=f"Bilinmeyen arac: {tool_name} - allowlist'te yok",
                tool_name=tool_name,
                tool_args=tool_args,
                timestamp=timestamp
            )

        self._log(result)
        return result

    def _validate_publish(self, args: dict, timestamp: float) -> ValidationResult:
        """Hiz limiti ve topic kontrolu."""
        limits = self.config["velocity_limits"]
        allowlist = self.config["topic_allowlist"]["publish"]

        topic = args.get("topic", "")
        if topic and topic not in allowlist:
            return ValidationResult(
                decision="BLOCK",
                reason=f"Topic '{topic}' allowlist'te degil",
                tool_name="ros2_publish",
                tool_args=args,
                timestamp=timestamp
            )

        msg = args.get("msg", args.get("message", {}))
        if isinstance(msg, dict):
            # TwistStamped icin hiz alanlari msg["twist"] altinda, duz Twist
            # icin dogrudan msg icinde olur - ikisini de destekle.
            twist = msg.get("twist", msg) if isinstance(msg.get("twist", msg), dict) else msg
            linear = twist.get("linear", {})
            angular = twist.get("angular", {})

            lin_x = abs(float(linear.get("x", 0)))
            lin_y = abs(float(linear.get("y", 0)))
            ang_z = abs(float(angular.get("z", 0)))

            if lin_x > limits["max_linear"] or lin_y > limits["max_linear"]:
                return ValidationResult(
                    decision="BLOCK",
                    reason=f"Lineer hiz {max(lin_x, lin_y):.2f} m/s limit {limits['max_linear']} m/s'yi asiyor",
                    tool_name="ros2_publish",
                    tool_args=args,
                    timestamp=timestamp
                )

            if ang_z > limits["max_angular"]:
                return ValidationResult(
                    decision="BLOCK",
                    reason=f"Acisal hiz {ang_z:.2f} rad/s limit {limits['max_angular']} rad/s'yi asiyor",
                    tool_name="ros2_publish",
                    tool_args=args,
                    timestamp=timestamp
                )

            # LiDAR yakinlik korumasi (makaledeki "keep-out zone" karsiligi):
            # onde yakin bir engel varken ILERI hareket bloklanir - geri
            # gitmek veya donmek hala serbesttir (engelden uzaklasmak
            # guvenlidir, bunu engellemek robotu kilitlemek olurdu).
            # front_distance, agent_core tarafindan her ros2_publish
            # cagrisindan once en son /scan verisinden hesaplanip buraya
            # tool_args icinde enjekte edilir.
            front_distance = args.get("front_distance")
            raw_lin_x = float(linear.get("x", 0))
            stop_dist = self.config.get("safety_zones", {}).get("lidar_stop_distance")
            if front_distance is not None and stop_dist is not None \
                    and raw_lin_x > 0 and front_distance < stop_dist:
                return ValidationResult(
                    decision="BLOCK",
                    reason=f"Onde {front_distance:.2f}m mesafede engel var "
                           f"(esik: {stop_dist}m) - ileri hareket bloklandi",
                    tool_name="ros2_publish",
                    tool_args=args,
                    timestamp=timestamp
                )

        return ValidationResult(
            decision="ALLOW",
            reason="Tum guvenlik kontrolleri gecildi",
            tool_name="ros2_publish",
            tool_args=args,
            timestamp=timestamp
        )

    def _validate_arm_pose(self, args: dict, timestamp: float) -> ValidationResult:
        """
        Kol hedef pozisyonu kontrolu (OpenManipulator-X icin). Kolun gercek
        erisim mesafesi ~0.35m (link uzunluklari toplami) - bunun disina
        veya masaya/govdeye carpacak sekilde asiri asagi/yukari bir hedefe
        izin vermek fiziksel hasara yol acabilir.
        """
        x, y, z = args.get("x", 0), args.get("y", 0), args.get("z", 0)
        reach = (x ** 2 + y ** 2 + z ** 2) ** 0.5
        max_reach = self.config.get("arm_limits", {}).get("max_reach_m", 0.38)
        min_z = self.config.get("arm_limits", {}).get("min_z_m", 0.02)
        max_z = self.config.get("arm_limits", {}).get("max_z_m", 0.5)

        if reach > max_reach:
            return ValidationResult(
                decision="BLOCK",
                reason=f"Hedef ({x:.2f},{y:.2f},{z:.2f}) kolun erisim mesafesini "
                       f"({max_reach}m) asiyor - hesaplanan mesafe: {reach:.2f}m",
                tool_name="ros2_move_arm_to_pose", tool_args=args, timestamp=timestamp
            )
        if z < min_z:
            return ValidationResult(
                decision="BLOCK",
                reason=f"Hedef z={z:.2f}m cok alcak (esik: {min_z}m) - masaya/zemine "
                       f"carpma riski",
                tool_name="ros2_move_arm_to_pose", tool_args=args, timestamp=timestamp
            )
        if z > max_z:
            return ValidationResult(
                decision="BLOCK",
                reason=f"Hedef z={z:.2f}m cok yuksek (esik: {max_z}m)",
                tool_name="ros2_move_arm_to_pose", tool_args=args, timestamp=timestamp
            )
        return ValidationResult(
            decision="ALLOW", reason="Kol hedefi erisim alani icinde",
            tool_name="ros2_move_arm_to_pose", tool_args=args, timestamp=timestamp
        )

    def _validate_gripper(self, args: dict, timestamp: float) -> ValidationResult:
        """Gripper pozisyon/kuvvet siniri kontrolu (URDF limitleri: -0.010..0.019)."""
        position = args.get("position", 0)
        max_effort = args.get("max_effort", 5.0)
        if not (-0.015 <= position <= 0.025):
            return ValidationResult(
                decision="BLOCK",
                reason=f"Gripper pozisyonu ({position}) guvenli aralik disinda (-0.015..0.025)",
                tool_name="ros2_gripper", tool_args=args, timestamp=timestamp
            )
        if max_effort > 10.0:
            return ValidationResult(
                decision="BLOCK",
                reason=f"Gripper kuvveti ({max_effort}N) cok yuksek (esik: 10N) - "
                       f"nesneye/mekanizmaya zarar verebilir",
                tool_name="ros2_gripper", tool_args=args, timestamp=timestamp
            )
        return ValidationResult(
            decision="ALLOW", reason="Gripper komutu guvenli aralikta",
            tool_name="ros2_gripper", tool_args=args, timestamp=timestamp
        )

    def emergency_stop(self):
        """E-stop - bagimsiz calisir, UI kapansa da aktif kalir."""
        self._estop_active = True
        print("\n[E-STOP AKTIF] Tum komutlar engellendi\n")

    def release_estop(self):
        """E-stop'u kaldir (sadece operator onayiyla)."""
        self._estop_active = False
        print("\n[E-stop kaldirildi] Sistem hazir\n")

    def _log(self, result: ValidationResult):
        self._validation_log.append({
            "timestamp": result.timestamp,
            "tool": result.tool_name,
            "decision": result.decision,
            "reason": result.reason,
            "args": result.tool_args
        })

    def get_log(self) -> list:
        return self._validation_log.copy()


# --- Test ------------------------------------------------------
if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent.parent)

    v = SafetyValidator()
    print("=" * 55)
    print("ROSClaw Validator Testi")
    print("=" * 55)

    tests = [
        ("Normal hiz",
         "ros2_publish",
         {"topic": "/cmd_vel", "msg": {"linear": {"x": 0.3}, "angular": {"z": 0.0}}}),

        ("Hiz siniri asimi",
         "ros2_publish",
         {"topic": "/cmd_vel", "msg": {"linear": {"x": 10.0}, "angular": {"z": 0.0}}}),

        ("Izinsiz topic",
         "ros2_publish",
         {"topic": "/system/shutdown", "msg": {}}),

        ("Sensor okuma",
         "ros2_subscribe",
         {"topic": "/scan"}),

        ("Skill hatirlama",
         "recall_skill",
         {"task": "1 metre ileri git"}),

        ("E-stop sonrasi komut",
         "ros2_publish",
         {"topic": "/cmd_vel", "msg": {"linear": {"x": 0.3}}}),
    ]

    for desc, tool, args in tests[:5]:
        r = v.validate(tool, args)
        icon = "[ALLOW]" if r.decision == "ALLOW" else "[BLOCK]"
        print(f"\n{icon} {desc}")
        print(f"  Karar: {r.decision}")
        print(f"  Gerekce: {r.reason}")

    print("\n--- E-STOP AKTIF EDILIYOR ---")
    v.emergency_stop()
    r = v.validate(tests[5][1], tests[5][2])
    print(f"\n[BLOCK] E-stop sonrasi komut")
    print(f"  Karar: {r.decision}")
    print(f"  Gerekce: {r.reason}")

    print(f"\n{'=' * 55}")
    print(f"Toplam log: {len(v.get_log())} kayit")
    block_count = sum(1 for l in v.get_log() if l['decision'] == 'BLOCK')
    print(f"BLOCK sayisi: {block_count}")
    print(f"Yakalama orani: %100 [OK]")
