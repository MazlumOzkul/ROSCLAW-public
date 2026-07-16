"""
ROSClaw RAG Bilgi Tabani

ROS2 dokumantasyonu ve robot manuellerini
yerel ChromaDB'ye gomer. Tamamen offline calisir.
"""

import os
import json
from pathlib import Path
import chromadb
from chromadb.utils import embedding_functions


class RAGKnowledgeBase:
    def __init__(self, db_path: str = "skills/knowledge_base"):
        Path(db_path).mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=db_path)
        try:
            emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="BAAI/bge-small-en-v1.5"
            )
        except Exception:
            emb_fn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            "ros2_knowledge", embedding_function=emb_fn
        )

    def add_document(self, content: str, source: str,
                     chunk_size: int = 500) -> int:
        """Belgeyi parcalara bol ve veritabanina ekle."""
        words = content.split()
        chunks = []
        for i in range(0, len(words), chunk_size):
            chunk = " ".join(words[i:i+chunk_size])
            chunks.append(chunk)

        ids = [f"{source}_{i}" for i in range(len(chunks))]
        existing = self.collection.get(ids=ids)
        existing_ids = set(existing["ids"])
        new_chunks = [(c, i) for c, i in zip(chunks, ids)
                      if i not in existing_ids]

        if new_chunks:
            self.collection.add(
                documents=[c for c, _ in new_chunks],
                ids=[i for _, i in new_chunks],
                metadatas=[{"source": source}] * len(new_chunks)
            )
        return len(new_chunks)

    def search(self, query: str, top_k: int = 3) -> str:
        """En ilgili parcalari bul ve dondur."""
        if self.collection.count() == 0:
            return "Bilgi tabani bos. Once belge ekle."
        results = self.collection.query(
            query_texts=[query], n_results=min(top_k, self.collection.count())
        )
        documents = results["documents"][0]
        sources = [m["source"] for m in results["metadatas"][0]]
        output = []
        for doc, src in zip(documents, sources):
            output.append(f"[{src}]\n{doc}")
        return "\n\n---\n\n".join(output)

    def add_ros2_basics(self):
        """Temel ROS2 bilgisini ekle."""
        basics = """
ROS2 Jazzy Temel Komutlar ve API Referansi

HAREKET KONTROLU:
/cmd_vel topic'i BU KURULUMDA (Jazzy + Gazebo Sim/ros_gz) duz
geometry_msgs/Twist DEGIL, geometry_msgs/msg/TwistStamped mesaji alir.
Hiz degerleri msg["twist"]["linear"/"angular"] altindadir, ayrica bos da
olsa bir "header" alani gerekir. Detay icin "rosclaw_gotchas" kaynagina bak.
linear.x (ileri/geri m/s), angular.z (donus rad/s).

Ornek ileri hareket (rosbridge/roslibpy JSON uzerinden):
ros2_publish("/cmd_vel",
    {"header": {}, "twist": {"linear": {"x": 0.3}, "angular": {"z": 0.0}}},
    "geometry_msgs/msg/TwistStamped")

LAZER SENSOR:
/scan topic'i sensor_msgs/LaserScan mesaji yayinlar.
ranges listesi mesafeleri metre cinsinden icerir.
Onde engel kontrolu: min(ranges[160:200])

ODOMETRI:
/odom topic'i nav_msgs/Odometry mesaji yayinlar.
Konum: pose.pose.position.x ve .y
Yon: pose.pose.orientation (quaternion)

TUTUCU KONTROLU:
/gripper/command topic'i std_msgs/Float64 alir.
0.0 = tam kapali, 1.0 = tam acik

NAV2 NAVIGASYON:
/navigate_to_pose action'i hedef konum alir.
goal.pose.position.x ve .y ile hedef belirlenir.

GUVENLIK LIMITLERI:
Maksimum lineer hiz: 0.5 m/s
Maksimum acisal hiz: 1.0 rad/s
LiDAR dur mesafesi: 0.3 metre
""".strip()
        added = self.add_document(basics, "ros2_basics")
        print(f"[OK] ROS2 temel bilgisi eklendi ({added} parca)")

    def add_reference_files(self, base_dir: str = "logs"):
        """logs/ altindaki referans notlarini (ros2_cli_reference.txt,
        ros2_interfaces.txt, rosclaw_gotchas.txt - hepsi depoda mevcut)
        RAG deposuna isler. Bu dosyalar oturumlar boyunca biriken gercek
        ROS2/Gazebo bilgisini icerir - onceden bir kerelik elle eklenmisti,
        kod olarak kayitli degildi; bu yuzden yeni bir klonda search_docs
        sadece add_ros2_basics'in tek parcasiyla kaliyordu. Bu fonksiyon
        o kaybi gideriyor - fresh bir depoda da ayni RAG icerigini kurar."""
        files = ["ros2_cli_reference.txt", "ros2_interfaces.txt", "rosclaw_gotchas.txt"]
        total = 0
        for fname in files:
            path = Path(base_dir) / fname
            if not path.exists():
                continue
            source = path.stem
            content = path.read_text(encoding="utf-8")
            added = self.add_document(content, source)
            total += added
            print(f"[OK] {fname} eklendi ({added} parca)")
        return total

    def delete_source(self, source: str) -> int:
        """Bir kaynaga ait tum parcalari sil (icerik guncellenip yeniden
        eklenecekse eski/yanlis parcalarin kalmamasi icin kullan)."""
        existing = self.collection.get(where={"source": source})
        ids = existing.get("ids", [])
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    def stats(self) -> dict:
        return {"total_documents": self.collection.count()}


if __name__ == "__main__":
    import os
    os.chdir(__import__("pathlib").Path(__file__).parent.parent)
    kb = RAGKnowledgeBase()
    kb.add_ros2_basics()
    result = kb.search("tutucuyu nasil acarim")
    print("\nArama sonucu: 'tutucuyu nasil acarim'")
    print("-" * 40)
    print(result[:500])
    print(f"\nIstatistik: {kb.stats()}")
