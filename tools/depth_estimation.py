"""
ROSClaw - Depth Anything V2 (Metric-Indoor-Small) ile tek RGB kareden
GERCEK (metre cinsinden) derinlik tahmini.

tools/object_detection.py'deki eski yontem (sabit bir duzlem yuksekligi
varsayip isin-duzlem kesisimi hesaplamak) yerine, burada modelin urettigi
GERCEK metrik derinlik haritasi kullanilir - nesnenin gercekte hangi
yukseklikte/mesafede oldugu varsayilmadan dogrudan olculur. "Metric-Indoor"
varyanti ozellikle ic-mekan robotik sahneleri icin egitilmis (max ~20m).

Model kucuk (25M parametre, ViT-S) - CPU'da tek kare icin makul sure
(~1-3 saniye). Ilk kullanimda HuggingFace'ten bir kere iner, sonrasinda
tamamen offline (yerel HF cache) calisir.
"""
import numpy as np
from PIL import Image

_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        from transformers import pipeline
        _pipe = pipeline(
            task="depth-estimation",
            model="depth-anything/Depth-Anything-V2-Metric-Indoor-Small-hf",
        )
    return _pipe


def estimate_depth_map(image_bgr: np.ndarray, max_dim: int = 256) -> np.ndarray:
    """
    BGR numpy goruntusunden, ORIJINAL boyuta yeniden olceklenmis metre-
    cinsinden derinlik haritasi (H x W float array) dondurur.

    max_dim: hizli CPU cikarimi icin goruntu bu boyuta kucultulur once
    (tam 640x480'de ~46s, 256px'e kucultunce ~9s - CPU'da pratik kullanim
    icin bu kucultme sart, dogruluk kaybı gorece kucuk).
    """
    import cv2
    h0, w0 = image_bgr.shape[:2]
    scale = max_dim / max(h0, w0)
    small = cv2.resize(image_bgr, (int(w0 * scale), int(h0 * scale))) if scale < 1 else image_bgr

    image_rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    pil_image = Image.fromarray(image_rgb)

    pipe = _get_pipe()
    result = pipe(pil_image)
    depth_tensor = result["predicted_depth"]

    depth_np = depth_tensor.squeeze().cpu().numpy() if hasattr(depth_tensor, "cpu") \
        else np.array(depth_tensor)

    if depth_np.shape != (h0, w0):
        depth_img = Image.fromarray(depth_np).resize((w0, h0), Image.BILINEAR)
        depth_np = np.array(depth_img)

    return depth_np


def depth_at_pixel(depth_map: np.ndarray, u: float, v: float,
                    window: int = 3) -> float:
    """Piksel (u,v) etrafinda kucuk bir pencerenin medyan derinligini
    dondurur (tek piksel gurultusune karsi daha saglam)."""
    h, w = depth_map.shape
    u_i, v_i = int(round(u)), int(round(v))
    u0, u1 = max(0, u_i - window), min(w, u_i + window + 1)
    v0, v1 = max(0, v_i - window), min(h, v_i + window + 1)
    patch = depth_map[v0:v1, u0:u1]
    return float(np.median(patch))
