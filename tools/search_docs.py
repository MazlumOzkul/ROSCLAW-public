"""
ROSClaw search_docs araci

Agent'in ihtiyac duydugu teknik bilgiyi (ROS2 API'leri, robot komutlari,
ornek kodlar) internete gitmeden, yerel ChromaDB RAG deposundan ceker.
Internet olmasa bile agent dogru sozdizimini/API'yi hatirlayabilir.
"""

from memory.rag_knowledge import RAGKnowledgeBase

_kb = None


def _get_kb() -> RAGKnowledgeBase:
    global _kb
    if _kb is None:
        _kb = RAGKnowledgeBase()
        if _kb.stats()["total_documents"] == 0:
            _kb.add_ros2_basics()
            _kb.add_reference_files()
    return _kb


def search_docs(query: str, top_k: int = 3) -> dict:
    """Yerel ROS2/robot dokumantasyonunda ara (tamamen offline)."""
    kb = _get_kb()
    result = kb.search(query, top_k=top_k)
    return {"status": "ok", "source": "local_rag", "query": query, "result": result}


if __name__ == "__main__":
    import os
    os.chdir(__import__("pathlib").Path(__file__).parent.parent)
    print("search_docs testi:")
    print("=" * 55)
    r = search_docs("cmd_vel ile robotu nasil hareket ettiririm")
    print(r["result"][:400])
    print("\n[OK] search_docs araci hazir")
