"""
ROSClaw - kamera tabanli, tamamen OFFLINE renk/nesne tespiti.

Buyuk bir ML modeli (YOLO vb.) yerine bilincli olarak basit HSV renk
esikleme kullanilir: deterministik, hizli, egitim/internet gerektirmez -
projenin "offline-first" felsefesiyle tutarli. Karmasik/rastgele nesne
tanima gerekirse bu, Claude API (vision) ile ONLINE bir yol olarak
ilerde eklenebilir; simdilik "kirmizi/mavi/yesil/sari topu bul" gibi
somut, renk-bazli komutlar icin yeterli ve saglam.

Kamera SABIT olarak govdeye monteli (donen bir parca degil), bu yuzden
base_link -> camera_rgb_optical_frame donusumu URDF'ten alinan SABIT
degerlerle (canli TF sorgusu gerekmeden) hesaplanabilir:
  base_link -> camera_rgb_frame   : xyz=(0.076, 0.0, 0.093), rpy=0
  camera_rgb_frame -> optical     : rpy=(-pi/2, 0, -pi/2)  (REP-103 standardi)
"""
import base64
import numpy as np
import cv2

# --- Sabit kamera disari (extrinsic) - waffle_pi urdf'inden ---
_CAMERA_POS_BASE = np.array([0.076, 0.0, 0.093])


def _euler_to_rot(roll, pitch, yaw) -> np.ndarray:
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    return rz @ ry @ rx


# camera_rgb_optical_frame'in base_link'e gore rotasyonu (optical -> base_link)
_ROT_BASE_FROM_OPTICAL = _euler_to_rot(-np.pi / 2, 0, -np.pi / 2)

_COLOR_RANGES = {
    # HSV (OpenCV: H 0-179, S/V 0-255)
    "kirmizi": [((0, 100, 80), (8, 255, 255)), ((172, 100, 80), (179, 255, 255))],
    "red": [((0, 100, 80), (8, 255, 255)), ((172, 100, 80), (179, 255, 255))],
    "mavi": [((100, 100, 60), (130, 255, 255))],
    "blue": [((100, 100, 60), (130, 255, 255))],
    "yesil": [((40, 80, 60), (85, 255, 255))],
    "green": [((40, 80, 60), (85, 255, 255))],
    "sari": [((22, 100, 100), (35, 255, 255))],
    "yellow": [((22, 100, 100), (35, 255, 255))],
}


def decode_ros_image(image_msg: dict) -> np.ndarray:
    """roslibpy'den gelen sensor_msgs/Image dict'ini (base64 'data' alani
    dahil) BGR numpy dizisine cevirir."""
    width = image_msg["width"]
    height = image_msg["height"]
    encoding = image_msg.get("encoding", "rgb8")
    raw = base64.b64decode(image_msg["data"])
    arr = np.frombuffer(raw, dtype=np.uint8)

    channels = 1 if "mono" in encoding else 3
    arr = arr.reshape((height, width, channels))
    if channels == 3 and encoding.startswith("rgb"):
        arr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    return arr


def find_color_centroid(image_bgr: np.ndarray, color: str,
                         min_area: int = 200) -> dict:
    """Verilen renk icin en buyuk blob'un piksel merkezini bulur."""
    color_key = color.strip().lower()
    if color_key not in _COLOR_RANGES:
        return {"found": False, "reason": f"Bilinmeyen renk: {color}. "
                                           f"Bilinenler: {list(_COLOR_RANGES.keys())}"}

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in _COLOR_RANGES[color_key]:
        mask |= cv2.inRange(hsv, np.array(lower), np.array(upper))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"found": False, "reason": f"'{color}' renginde nesne bulunamadi"}

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    if area < min_area:
        return {"found": False, "reason": f"'{color}' rengi bulundu ama cok kucuk "
                                           f"(alan={area:.0f}px, esik={min_area}px)"}

    M = cv2.moments(largest)
    u = M["m10"] / M["m00"]
    v = M["m01"] / M["m00"]
    return {"found": True, "pixel": {"u": u, "v": v}, "area_px": float(area)}


def pixel_to_ground_point(u: float, v: float, camera_info: dict,
                           plane_z: float = 0.0) -> dict:
    """
    Piksel (u,v) + kamera icsel kalibrasyonu (camera_info K matrisi) kullanarak,
    base_link cercevesinde z=plane_z duzlemiyle kesisen 3D noktayi hesaplar.
    YAKLASIKLIK: nesnenin gercekten bu sabit yukseklikteki bir yuzeyde
    (masa/zemin) durdugu varsayilir - gercek derinlik olcumu (RGBD/stereo)
    YOKTUR, tek RGB kameradan gercek derinlik cikarilamaz.
    """
    K = camera_info["k"] if "k" in camera_info else camera_info["K"]
    fx, fy, cx, cy = K[0], K[4], K[2], K[5]

    # Piksel -> optical cercevede normalize edilmis isin yonu (Z=1 ileri)
    ray_optical = np.array([(u - cx) / fx, (v - cy) / fy, 1.0])
    ray_base = _ROT_BASE_FROM_OPTICAL @ ray_optical

    if abs(ray_base[2]) < 1e-6:
        return {"found": False, "reason": "Isin duzleme paralel - kesisim yok"}

    t = (plane_z - _CAMERA_POS_BASE[2]) / ray_base[2]
    if t <= 0:
        return {"found": False, "reason": "Hesaplanan nokta kameranin arkasinda "
                                           "(negatif mesafe) - plane_z yanlis olabilir"}

    point = _CAMERA_POS_BASE + t * ray_base
    return {"found": True, "x": float(point[0]), "y": float(point[1]), "z": float(point[2])}
