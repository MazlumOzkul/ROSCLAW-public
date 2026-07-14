"""
ROSClaw - kavrama fizibilite kontrolu.

ONEMLI DONANIM GERCEGI: OpenManipulator-X'in bilekte DONDURME (roll)
ekseni YOK - sadece taban-yaw + 3 pitch eklemi var (bkz. arm_kinematics.py).
Bu yuzden GG-CNN gibi "kavrama acisi" tahmin eden gelismis modeller bu
donanimda FIZIKSEL OLARAK UYGULANAMAZ - gripper'i istedigimiz aciya
ceviremiyoruz. Bunun yerine cok daha mutevazi ama DURUST bir kontrol
yapiyoruz: nesnenin tahmini genisligi gripper'in bilinen maksimum
acikligini asiyorsa, sahte bir "basarili" gorunumu vermek yerine acikca
"bu nesneyi tutamam" diyoruz.

Gripper acikligi: onceden (bu dosyanin ilk halinde) 4.5cm'lik KABA bir
tahminti. Gercek deger, ROBOTIS'in resmi ROS2 paketindeki (donanimda da
kullanilan) URDF + STL mesh'inden GEOMETRIK olarak hesaplandi:

- `gripper_left_joint` (prismatic, eksen +y, orijin y=0.021m) komut
  araligi -0.010..0.019m (open_manipulator_x.urdf.xacro).
- `gripper_left_palm.stl` mesh'inin kendi yerel cercevesindeki y araligi
  -12.15mm .. +27.6mm (mesh, eklem orijinine gore konumlaniyor).
- Parmak TAM ACIK (joint=+0.019m) durumunda ic (nesneye bakan) kenar:
  0.021 + 0.019 - 0.01215 = 0.02785m eksen merkezinden.
- Simetrik sag parmakla bosluk: 2 x 0.02785 = 0.0557m (~5.57cm).

Bu, statik CAD geometrisinden hesaplanan TEORIK ust sinir - gercek
donanimda backlash/pad esnekligi/STL'in tam temas yuzeyini yansitmamasi
gibi nedenlerle biraz daha az olabilir, bu yuzden kucuk bir guvenlik payi
dusulerek kullanildi. Gercek robotta fiziksel olarak dogrulanmasi onerilir.
"""

MAX_GRASP_WIDTH_M = 0.05  # gercek URDF+mesh geometrisinden hesaplandi (~5.57cm), guvenlik payiyla 5.0cm


def estimate_object_width_m(bbox_width_px: float, depth_m: float, fx: float) -> float:
    """Piksel genisligi + derinlik + kameranin fx (odak uzakligi, camera_info.K[0])
    kullanarak nesnenin gercek dunyadaki genisligini (metre) tahmin eder."""
    if fx <= 0 or depth_m <= 0:
        return 0.0
    return bbox_width_px * depth_m / fx


def check_graspability(object_width_m: float) -> dict:
    """Nesnenin gripper'in fiziksel acikligina sigip sigmadigini kontrol eder."""
    if object_width_m > MAX_GRASP_WIDTH_M:
        return {
            "graspable": False,
            "reason": f"Nesne cok genis (~{object_width_m*100:.1f}cm) - "
                      f"gripper'in maksimum acikligi (~{MAX_GRASP_WIDTH_M*100:.1f}cm) "
                      f"yetersiz, tutmaya calismak basarisiz olur/nesneye zarar verebilir",
        }
    return {"graspable": True, "width_estimate_m": object_width_m}
