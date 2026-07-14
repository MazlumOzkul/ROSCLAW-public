"""
ROSClaw Skill Kutuphanesi - VOYAGER tarzi deneyim hafizasi

Basarili (gorev -> kod) ciftlerini saklar.
Benzer gorev gelince LLM'yi atlar, direkt kodu dondurur.
"""

from __future__ import annotations
import json, time, hashlib, re
from pathlib import Path
import numpy as np


class HashingEmbedder:
    """Sifir-bagimlilik fallback. sentence-transformers yoksa kullan."""
    suggested_threshold = 0.45
    def __init__(self, dim: int = 384):
        self.dim = dim
    def encode(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"\w+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec


class SentenceTransformerEmbedder:
    """Uretim embedder'i - parafrazlari da yakalar."""
    suggested_threshold = 0.75
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model)
    def encode(self, text: str) -> np.ndarray:
        return self.model.encode(text, normalize_embeddings=True).astype(np.float32)


def default_embedder():
    try:
        return SentenceTransformerEmbedder()
    except Exception:
        print("[WARN] sentence-transformers yok, HashingEmbedder kullaniliyor")
        return HashingEmbedder()


class SkillLibrary:
    """Robotun kalici beceri hafizasi."""

    def __init__(self, path: str = "skills/robot_skills.json",
                 embedder=None, similarity_threshold: float = None):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        self.embedder = embedder or default_embedder()
        self.threshold = (similarity_threshold if similarity_threshold is not None
                          else getattr(self.embedder, "suggested_threshold", 0.6))
        self.skills: list[dict] = []
        self._vectors = None
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.skills = data.get("skills", [])
            self._rebuild_cache()

    def _save(self):
        self.path.write_text(json.dumps({"skills": self.skills},
                                        indent=2, ensure_ascii=False), encoding="utf-8")

    def _rebuild_cache(self):
        self._vectors = (np.array([s["embedding"] for s in self.skills],
                                  dtype=np.float32) if self.skills else None)

    # Karsilikli disleyici kelime kategorileri - embedding benzerligi yuksek
    # cikse bile (orn. "ileri git" ile "geri git" cosine benzerligi ~0.94,
    # "mavi topu al" ile "kirmizi topu al" de yuksek cikabiliyor), sorgu ve
    # onbellekteki gorev AYNI KATEGORIDEN FARKLI kelimeler iceriyorsa eslesme
    # reddedilir. Yeni bir ayrim turu (orn. baska bir renk, baska bir yon)
    # bulunursa buraya yeni bir kume eklemek yeterli - saf embedding robotik
    # komutlar icin tek basina guvenli degil.
    EXCLUSIVE_CATEGORIES = [
        {"ileri", "forward", "geri", "backward", "backwards"},
        {"sag", "right", "sol", "left"},
        {"ac", "acik", "open", "kapat", "kapali", "kapa", "close", "closed"},
        {"yukari", "up", "asagi", "down"},
        {"dur", "stop", "git", "go", "start"},
        {"artir", "increase", "azalt", "decrease"},
        {"hizlan", "speed", "yavasla", "slow"},
        {"kirmizi", "red", "mavi", "blue", "yesil", "green", "sari", "yellow",
         "siyah", "black", "beyaz", "white", "turuncu", "orange", "mor", "purple",
         "pembe", "pink", "gri", "gray", "grey"},
        {"al", "tut", "kaldir", "pick", "take", "grab", "hold",
         "birak", "bırak", "drop", "release", "koy", "put"},
    ]

    def _numbers(self, text: str) -> set:
        return set(re.findall(r"\d+(?:\.\d+)?", text))

    def _has_conflicting_opposite(self, query: str, candidate: str) -> bool:
        q_words = set(re.findall(r"\w+", query.lower()))
        c_words = set(re.findall(r"\w+", candidate.lower()))
        for category in self.EXCLUSIVE_CATEGORIES:
            q_hit = q_words & category
            c_hit = c_words & category
            if q_hit and c_hit and q_hit != c_hit:
                return True
        return False

    def recall(self, task: str) -> dict | None:
        if not self.skills or self._vectors is None:
            return None
        q = self.embedder.encode(task)
        sims = self._vectors @ q
        order = np.argsort(-sims)
        for idx in order:
            score = float(sims[idx])
            if score < self.threshold:
                break
            s = self.skills[idx]
            # Guvenlik guardi: sayilar uyusmuyorsa veya zit yon/eylem
            # kelimeleri varsa bu eslesmeyi reddet, siradaki adaya bak.
            if self._numbers(task) != self._numbers(s["task"]):
                continue
            if self._has_conflicting_opposite(task, s["task"]):
                continue
            return {"task": s["task"], "code": s["code"],
                    "similarity": round(score, 3), "uses": s["success_count"]}
        return None

    def save(self, task: str, code: str, **meta) -> str:
        key = hashlib.md5(task.encode()).hexdigest()[:12]
        for s in self.skills:
            if s["id"] == key:
                s["success_count"] += 1
                s["code"] = code
                s["updated"] = time.time()
                self._save()
                return key
        emb = self.embedder.encode(task)
        self.skills.append({"id": key, "task": task, "code": code,
                             "embedding": emb.tolist(), "success_count": 1,
                             "created": time.time(), "updated": time.time(), **meta})
        self._rebuild_cache()
        self._save()
        return key

    def list_skills(self) -> list:
        return sorted([{"task": s["task"], "uses": s["success_count"]}
                       for s in self.skills], key=lambda x: -x["uses"])

    def stats(self) -> dict:
        return {"total_skills": len(self.skills),
                "total_uses": sum(s["success_count"] for s in self.skills),
                "embedder": type(self.embedder).__name__,
                "threshold": self.threshold}


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent.parent)

    lib = SkillLibrary()
    print("Skill Library Testi")
    print("=" * 55)
    lib.save("1 metre ileri git", "publish('/cmd_vel', linear_x=0.3); sleep(3.3); stop()")
    r = lib.recall("1 metre ileri git")
    print("[OK] Kaydedildi ve bulundu" if r else "[ERR] Bulunamadi")
    r2 = lib.recall("bir metre ileriye ilerle")
    print(f"Parafraz testi (\"bir metre ileriye ilerle\"): {'[OK] bulundu, benzerlik=' + str(r2['similarity']) if r2 else '[--] esik altinda kaldi (bekleniyor - embedder tipine bagli)'}")
    print(lib.stats())
