"""
ROSClaw Hibrit Model Router

Gorev karmasikligina ve internet erisimine gore
dogru modele yonlendirme yapar.
Internet varsa + gorev karmasiksa -> Claude API (frontier)
Yoksa -> yerel Ollama modeli (qwen2.5-coder, tam offline)

Karmasiklik sadece kelime sayisi/anahtar kelimeyle degil, TANIDIKLIK ile de
olculur: "kolunu kaldir ve salla" gibi kisa ama SYSTEM_PROMPT'taki hicbir
ORNEK kaliba benzemeyen (dolayisiyla Qwen'in yanlis yorumlama riski yuksek
olan) talimatlar, kelime sayisi dusuk gorunse bile Claude'a yonlendirilir.
Boylece her yeni gorev turu icin elle ornek eklemek yerine, "bilinen kaliba
uzak" olan HER SEY otomatik olarak daha guclu modele kayar - internetten
bilgi cekmekten farkli olarak sonuc hala bizim ozel arac arayuzumuze
(ros2_move_arm_to_pose vb.) gore uretiliyor.
"""

import os
import yaml
import requests
import re
from typing import Optional

# core/agent_core.py SYSTEM_PROMPT'undaki ORNEK 1-8 talimatlarinin ozeti -
# Qwen'in iyi kapsadigi bilinen gorev kaliplari. Yeni bir ORNEK eklendiginde
# buraya da eklenmesi onerilir (skill_library'nin embedding'iyle ayni mantik).
_KNOWN_PATTERNS = [
    "0.5 metre ileri git",
    "90 derece sola don",
    "onde engel var mi kontrol et",
    "kirmizi topu al",
    "bardagi al",
    "mutfaga git",
    "burasi mutfak, kaydet",
    "merhaba, nasilsin?",
    "dur",
    "geri git",
]


class ModelRouter:
    def __init__(self, config_path: str = "config/model_config.yaml"):
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self.ollama_url = os.environ.get(
            "OLLAMA_BASE_URL", "http://localhost:11434")
        self._embedder = None
        self._pattern_vectors = None

    def _get_embedder(self):
        if self._embedder is None:
            from memory.skill_library import default_embedder
            self._embedder = default_embedder()
            self._pattern_vectors = [self._embedder.encode(p) for p in _KNOWN_PATTERNS]
        return self._embedder

    def _novelty_score(self, instruction: str) -> float:
        """Talimat, bilinen hicbir ORNEK kaliba yeterince benzemiyorsa 1.0
        (tanidik degil -> Claude'a yonlendirilmeli), benziyorsa 0.0 dondurur."""
        embedder = self._get_embedder()
        q = embedder.encode(instruction)
        best = max(float(q @ v) for v in self._pattern_vectors)
        threshold = getattr(embedder, "suggested_threshold", 0.6)
        return 0.0 if best >= threshold else 1.0

    def route(self, instruction: str, context: dict = None) -> str:
        """Goreve uygun modeli sec ve cagir."""
        complexity = self._complexity_score(instruction)
        threshold = self.config["routing"]["complexity_threshold"]
        if self._novelty_score(instruction) > 0.0:
            # Bilinen hicbir kaliba benzemiyor - kisa/basit gorunse bile
            # esigi zorlayarak daha guclu modele sansi verilsin.
            complexity = max(complexity, threshold)
        internet = self._internet_available()

        if complexity >= threshold and internet:
            print(f"  -> Claude API (karmasiklik: {complexity:.2f})")
            response = self._call_claude(instruction, context)
            if response:
                return response
            print("  [FALLBACK] Claude basarisiz, Qwen'e dusuyor")

        print(f"  -> Qwen2.5-Coder (karmasiklik: {complexity:.2f}, offline)")
        return self._call_ollama(instruction, context,
                                  self.config["models"]["coder"]["model"])

    def _complexity_score(self, instruction: str) -> float:
        """0.0 (basit) ile 1.0 (cok karmasik) arasinda skor."""
        score = 0.0
        words = len(instruction.split())

        score += min(words / 30.0, 0.3)

        vague = ["belki", "eger", "ya da", "veya", "sanirim",
                 "muhtemelen", "maybe", "if", "or", "perhaps"]
        for word in vague:
            if word in instruction.lower():
                score += 0.1

        multi = ["once", "sonra", "ardindan", "ve", "then", "after", "before"]
        for word in multi:
            if word in instruction.lower():
                score += 0.05

        logic = ["analiz", "degerlendir", "karar ver", "planla",
                 "neden", "nasil", "karsilastir", "analyze", "evaluate"]
        for word in logic:
            if word in instruction.lower():
                score += 0.15

        return min(score, 1.0)

    def _internet_available(self) -> bool:
        """Internet baglantisini kontrol et."""
        try:
            requests.get("https://api.anthropic.com", timeout=2)
            return True
        except Exception:
            return False

    def _call_ollama(self, instruction: str, context: dict,
                     model: str) -> Optional[str]:
        try:
            messages = [{"role": "user", "content": instruction}]
            if context and context.get("history"):
                messages = context["history"] + messages
            payload = {"model": model, "messages": messages,
                       "stream": False,
                       "options": {"temperature": 0.1}}
            r = requests.post(f"{self.ollama_url}/api/chat",
                              json=payload, timeout=60)
            return r.json()["message"]["content"]
        except Exception as e:
            print(f"Ollama hatasi: {e}")
            return None

    def _call_claude(self, instruction: str, context: dict) -> Optional[str]:
        try:
            import anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key or api_key == "your_claude_api_key_here":
                return None
            client = anthropic.Anthropic(api_key=api_key)
            message = client.messages.create(
                model=self.config["models"]["frontier"]["model"],
                max_tokens=2048,
                messages=[{"role": "user", "content": instruction}]
            )
            return message.content[0].text
        except Exception as e:
            print(f"Claude API hatasi: {e}")
            return None


if __name__ == "__main__":
    import os
    os.chdir(__import__("pathlib").Path(__file__).parent.parent)
    router = ModelRouter()

    tests = [
        "1 metre ileri git",
        "Ortami analiz et, tehlikeli nesneleri belirle ve guvenli bir rota planla",
        "rafi duzenle"
    ]
    print("Model Router Testi:")
    for t in tests:
        score = router._complexity_score(t)
        internet = router._internet_available()
        model = "Claude API" if score >= 0.7 and internet else "Qwen (local)"
        label = f"'{t[:40]}...'" if len(t) > 40 else f"'{t}'"
        print(f"\n{label}")
        print(f"  Karmasiklik: {score:.2f} | Internet: {internet} | Model: {model}")
