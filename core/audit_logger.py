"""
ROSClaw Audit Logger - L katmani (C = <A, O, V, L> sozlesmesi)

arXiv 2603.26997 makalesindeki formul birebir uygulanir:
    l_t = (t, o_t, u_t, d_t, r_t, y_t)
      t   - zaman damgasi
      o_t - karar aninda bilinen gozlem (orn. onde engel mesafesi)
      u_t - onerilen arac cagrisi (tool_name + args)
      d_t - karar (ALLOW/BLOCK)
      r_t - gerekce
      y_t - calisma sonucu ("success"/"error"/None - BLOCK edildiyse hic
            calismadi, bu yuzden None: makaledeki "y_t is the execution
            outcome (or the empty set if blocked)" ifadesinin karsiligi)

I3 (Auditability) invariant'i: engellenen eylemler bile, calismadan once
kaydedilir - post-hoc analiz icin hicbir girisim kaybolmaz. Append-only
JSONL dosyasina yazilir (satir satir JSON, diske hemen flush edilir).
"""

import json
import time
from pathlib import Path
from threading import Lock


class AuditLogger:
    def __init__(self, path: str = "logs/audit_log.jsonl"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def log(self, observation: dict, tool_name: str, tool_args: dict,
            decision: str, reason: str, outcome: str = None) -> dict:
        entry = {
            "t": time.time(),
            "o_t": observation,
            "u_t": {"tool": tool_name, "args": tool_args},
            "d_t": decision,
            "r_t": reason,
            "y_t": outcome,
        }
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        return entry

    def read_all(self) -> list:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(ln) for ln in lines if ln.strip()]

    def stats(self) -> dict:
        """Faz 10/Auto-EAP tarzi ozet: karar/sonuc dagilimi, en cok BLOCK
        edilen arac/gerekceler - "en cok hata veren kategori" raporunun temeli."""
        entries = self.read_all()
        block_reasons = {}
        outcomes = {"success": 0, "error": 0, "none": 0}
        tool_counts = {}
        for e in entries:
            tool_counts[e["u_t"]["tool"]] = tool_counts.get(e["u_t"]["tool"], 0) + 1
            if e["d_t"] == "BLOCK":
                block_reasons[e["r_t"]] = block_reasons.get(e["r_t"], 0) + 1
            outcomes[e["y_t"] or "none"] = outcomes.get(e["y_t"] or "none", 0) + 1
        return {
            "total_entries": len(entries),
            "total_blocked": sum(1 for e in entries if e["d_t"] == "BLOCK"),
            "outcomes": outcomes,
            "tool_counts": tool_counts,
            "top_block_reasons": sorted(block_reasons.items(), key=lambda x: -x[1])[:10],
        }


if __name__ == "__main__":
    import os
    os.chdir(Path(__file__).parent.parent)
    test_path = "logs/test_audit.jsonl"
    Path(test_path).unlink(missing_ok=True)
    logger = AuditLogger(path=test_path)
    logger.log({"front_distance": 1.2}, "ros2_publish", {"topic": "/cmd_vel"}, "ALLOW", "Guvenli", outcome="success")
    logger.log({"front_distance": 0.1}, "ros2_publish", {"topic": "/cmd_vel"}, "BLOCK", "Engel cok yakin", outcome=None)
    print("Kayitlar:", logger.read_all())
    print("Istatistik:", logger.stats())
    Path(test_path).unlink(missing_ok=True)
    print("\n[OK] AuditLogger hazir")
