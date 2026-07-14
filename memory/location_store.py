"""
ROSClaw Isimli Konum Deposu - navigasyon icin.

memory/robot_profiles.py ile AYNI kalici JSON-store desenini kullanir,
ama robot baglantilari yerine ISIMLI KONUMLARI (map cercevesinde x,y,yaw)
saklar - "mutfak", "salon" gibi. Kullanici bir konuma robotu goturup
ros2_save_location("mutfak") diyerek o anki pozisyonu kaydeder (WiFi ag
kaydetmek gibi - "burasi mutfak" der, sistem konumu hatirlar), sonra
"mutfaga git" dedigimde ros2_navigate_to_location("mutfak") bu kayitli
pozisyonu cozup Nav2'ye gonderir.
"""
from __future__ import annotations
import json, time, uuid
from pathlib import Path


class LocationStore:
    """Kaydedilmis isimli konumlari (map cercevesinde x,y,yaw) yonetir."""

    def __init__(self, path: str = "config/locations.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.locations: list[dict] = []
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.locations = data.get("locations", [])

    def _save(self):
        self.path.write_text(json.dumps(
            {"locations": self.locations}, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_locations(self) -> list:
        return self.locations

    def get_by_name(self, name: str) -> dict | None:
        name_norm = name.strip().lower()
        for loc in self.locations:
            if loc["name"].strip().lower() == name_norm:
                return loc
        return None

    def save(self, name: str, x: float, y: float, yaw: float = 0.0) -> str:
        """Yeni bir konum kaydeder, ayni isim varsa GUNCELLER (uzerine yazar)."""
        existing = self.get_by_name(name)
        if existing:
            existing.update({"x": x, "y": y, "yaw": yaw, "updated_at": time.time()})
            self._save()
            return existing["id"]

        loc_id = uuid.uuid4().hex[:12]
        self.locations.append({
            "id": loc_id, "name": name, "x": x, "y": y, "yaw": yaw,
            "created_at": time.time(), "updated_at": time.time(),
        })
        self._save()
        return loc_id

    def delete(self, name: str) -> bool:
        before = len(self.locations)
        name_norm = name.strip().lower()
        self.locations = [l for l in self.locations if l["name"].strip().lower() != name_norm]
        self._save()
        return len(self.locations) < before


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent.parent)
    test_path = "logs/test_locations.json"
    Path(test_path).unlink(missing_ok=True)

    store = LocationStore(path=test_path)
    store.save("mutfak", 1.5, 1.5, 0.0)
    store.save("salon", -1.5, 0.0, 0.0)
    print("Kayitli konumlar:", store.list_locations())
    print("mutfak ara:", store.get_by_name("Mutfak"))  # buyuk/kucuk harf farki test
    print("olmayan konum:", store.get_by_name("bahce"))
    store.delete("salon")
    print("silme sonrasi:", [l["name"] for l in store.list_locations()])

    Path(test_path).unlink(missing_ok=True)
    print("\n[OK] LocationStore hazir")
