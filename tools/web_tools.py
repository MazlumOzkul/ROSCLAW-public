"""
ROSClaw web_search araci

Internet varsa ek bilgi kaynagi olarak kullanilir (guncel bilgi, eksik
dokumantasyon, karmasik muhakeme gerektiren durumlar icin). Internet
yoksa veya arama basarisiz olursa otomatik olarak search_docs'a (yerel
RAG) duser - agent hicbir zaman bilgisiz kalmaz.
"""

import re
import requests

from tools.search_docs import search_docs

_SEARCH_URL = "https://html.duckduckgo.com/html/"


def _internet_available() -> bool:
    try:
        requests.get("https://api.anthropic.com", timeout=2)
        return True
    except Exception:
        return False


def web_search(query: str, max_results: int = 3) -> dict:
    """
    Internet aramasi yap. Internet yoksa veya basarisiz olursa
    yerel dokumantasyona (search_docs) duser.
    """
    if not _internet_available():
        fallback = search_docs(query)
        fallback["source"] = "local_rag_fallback"
        fallback["reason"] = "internet yok"
        return fallback

    try:
        resp = requests.post(
            _SEARCH_URL,
            data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (ROSClaw agent)"},
            timeout=6,
        )
        resp.raise_for_status()
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</a>', resp.text, re.DOTALL
        )
        clean = [re.sub(r"<.*?>", "", s).strip() for s in snippets[:max_results]]
        clean = [s for s in clean if s]

        if not clean:
            fallback = search_docs(query)
            fallback["source"] = "local_rag_fallback"
            fallback["reason"] = "web sonucu bulunamadi"
            return fallback

        return {
            "status": "ok",
            "source": "web",
            "query": query,
            "result": "\n\n---\n\n".join(clean),
        }
    except Exception as e:
        fallback = search_docs(query)
        fallback["source"] = "local_rag_fallback"
        fallback["reason"] = f"web arama hatasi: {e}"
        return fallback


if __name__ == "__main__":
    import os
    os.chdir(__import__("pathlib").Path(__file__).parent.parent)
    print("web_search testi:")
    print("=" * 55)
    print(f"Internet mevcut: {_internet_available()}")
    r = web_search("ROS2 Jazzy Nav2 navigate_to_pose action example")
    print(f"Kaynak: {r['source']}")
    print((r.get("result") or "")[:400])
    print("\n[OK] web_search araci hazir")
