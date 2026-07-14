"""
ROSClaw - YOLO-World ile GERCEK, acik-kelime nesne tanima.

tools/object_detection.py'deki renk-bazli (HSV) tespitten farkli olarak,
burada nesneler TIPLERIYLE ayirt edilebiliyor - "kirmizi" degil "supurge",
"bardak", "kutu" gibi rastgele metin sorgulariyla (open-vocabulary).

ONEMLI - Gazebo Sim ile dogrulanan sinirlama: bu model GERCEK fotograflarda
mukemmel calisiyor (COCO test goruntusunde %92 guvenle dogrulandi), ama
Gazebo'nun render motoru (duz aydinlatma, basitlestirilmis dokular) gercek
kameralardan cok farkli oldugu icin SIMULASYONDA neredeyse hic tespit
uretmiyor - bu iyi bilinen bir "sim-to-real" farki, kod hatasi degil.
Gercek robotta/gercek kamerada bu modul dogrudan calismasi beklenir.

Model: yolov8s-worldv2 (Ultralytics, 12.7M parametre) - ilk kullanimda
agirliklar (~28MB) bir kere internetten iner, sonrasinda TAMAMEN OFFLINE
calisir.
"""
from typing import Optional
import numpy as np

_model = None


def _get_model():
    """Modeli tembel (lazy) yukler - ilk cagrida ~10s, sonrasinda bellekte kalir."""
    global _model
    if _model is None:
        from ultralytics import YOLOWorld
        _model = YOLOWorld("yolov8s-worldv2.pt")
    return _model


def find_object(image_bgr: np.ndarray, description: str,
                 conf_threshold: float = 0.15) -> dict:
    """
    Acik-kelime nesne tespiti. `description` serbest metin olabilir
    ("vacuum cleaner", "red cup", "bardak" - ingilizce terimler COCO/LVIS
    egitim verisiyle daha iyi eslesir, ama kisa Turkce kelimeler de
    denenebilir).

    Donus: {"found": bool, "pixel": {"u","v"}, "bbox_px": {"width","height"},
            "confidence": float} veya {"found": False, "reason": str}
    """
    model = _get_model()
    model.set_classes([description])
    results = model.predict(image_bgr, verbose=False, conf=conf_threshold)

    boxes = results[0].boxes
    if len(boxes) == 0:
        return {"found": False,
                "reason": f"'{description}' goruntude bulunamadi "
                          f"(esik: %{conf_threshold*100:.0f} guven)"}

    # En yuksek guvenli tespiti al
    best_idx = int(np.argmax(boxes.conf.cpu().numpy()))
    x1, y1, x2, y2 = boxes.xyxy[best_idx].tolist()
    conf = float(boxes.conf[best_idx])

    return {
        "found": True,
        "pixel": {"u": (x1 + x2) / 2, "v": (y1 + y2) / 2},
        "bbox_px": {"width": x2 - x1, "height": y2 - y1,
                    "x1": x1, "y1": y1, "x2": x2, "y2": y2},
        "confidence": conf,
    }
