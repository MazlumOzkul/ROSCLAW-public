"""
ROSClaw - OpenManipulator-X (turtlebot3_manipulation kolu) icin basit
ileri/ters kinematik.

MoveIt2 entegrasyonu vendor'un turtlebot3_manipulation_moveit_config
paketindeki bir parametre coz├╝mleme sorunu (move_group "planning_plugin
bos" hatasiyla cokuyor, kok nedeni rclcpp'nin ic parametre isimlendirmesinde -
bilinen/kayitli bir sinirlama, daha fazla arastirma gerektiriyor) yuzunden
su an calismiyor. Bunun yerine, bu modul dogrudan FollowJointTrajectory
action'ina (zaten test edilip calistigi dogrulanmis) gonderilecek eklem
acilarini hesaplamak icin sayisal (numerik) IK cozer - MoveIt2/ROS'a hic
bagimli degil, saf numpy/scipy.

Zincir (open_manipulator_x.urdf.xacro'dan alinan gercek degerler):
  base_link -> link1   : sabit,          xyz=(-0.092, 0.0, 0.091)
  link1 -> link2 (j1)  : Z ekseni doner,  xyz=( 0.012, 0.0, 0.017)
  link2 -> link3 (j2)  : Y ekseni doner,  xyz=( 0.0,   0.0, 0.0595)
  link3 -> link4 (j3)  : Y ekseni doner,  xyz=( 0.024, 0.0, 0.128)
  link4 -> link5 (j4)  : Y ekseni doner,  xyz=( 0.124, 0.0, 0.0)
  link5 -> end_effector: sabit,           xyz=( 0.126, 0.0, 0.0)
"""
import numpy as np
from scipy.optimize import least_squares

# Vendor URDF'inden birebir alinan sabit eklem/segment ofsetleri.
_BASE_OFFSET = np.array([-0.092, 0.0, 0.091])
_J1_OFFSET = np.array([0.012, 0.0, 0.017])
_J2_OFFSET = np.array([0.0, 0.0, 0.0595])
_J3_OFFSET = np.array([0.024, 0.0, 0.128])
_J4_OFFSET = np.array([0.124, 0.0, 0.0])
_EE_OFFSET = np.array([0.126, 0.0, 0.0])

JOINT_LIMITS = {
    "joint1": (-0.9 * np.pi, 0.9 * np.pi),
    "joint2": (-0.57 * np.pi, 0.5 * np.pi),
    "joint3": (-0.3 * np.pi, 0.44 * np.pi),
    "joint4": (-0.57 * np.pi, 0.65 * np.pi),
}


def _rot_z(theta: float) -> np.ndarray:
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _rot_y(theta: float) -> np.ndarray:
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def forward_kinematics(q1: float, q2: float, q3: float, q4: float) -> np.ndarray:
    """Verilen 4 eklem acisi icin end_effector'un base_link cercevesindeki
    (x, y, z) konumunu dondurur."""
    pos = _BASE_OFFSET.copy()
    rot = np.eye(3)

    pos = pos + rot @ _J1_OFFSET
    rot = rot @ _rot_z(q1)

    pos = pos + rot @ _J2_OFFSET
    rot = rot @ _rot_y(q2)

    pos = pos + rot @ _J3_OFFSET
    rot = rot @ _rot_y(q3)

    pos = pos + rot @ _J4_OFFSET
    rot = rot @ _rot_y(q4)

    pos = pos + rot @ _EE_OFFSET
    return pos


def inverse_kinematics(x: float, y: float, z: float,
                        initial_guess: tuple = (0.0, 0.0, 0.0, 0.0)) -> dict:
    """
    Hedef (x, y, z) noktasi icin (joint1..joint4) acilarini sayisal olarak
    cozer (damped least squares / Levenberg-Marquardt, scipy uzerinden).

    Donus: {"success": bool, "joints": [j1,j2,j3,j4], "error_m": float,
            "reason": str (basarisizsa)}
    """
    target = np.array([x, y, z])

    def residual(q):
        return forward_kinematics(*q) - target

    bounds_lower = [JOINT_LIMITS[j][0] for j in ("joint1", "joint2", "joint3", "joint4")]
    bounds_upper = [JOINT_LIMITS[j][1] for j in ("joint1", "joint2", "joint3", "joint4")]

    result = least_squares(
        residual, x0=list(initial_guess),
        bounds=(bounds_lower, bounds_upper),
        method="trf", max_nfev=2000,
    )

    final_error = float(np.linalg.norm(residual(result.x)))
    if final_error > 0.02:  # 2cm'den fazla hata - hedefe ulasilamadi
        return {
            "success": False,
            "joints": result.x.tolist(),
            "error_m": final_error,
            "reason": f"Hedefe ulasilamadi (kalan hata: {final_error*100:.1f}cm) - "
                      f"muhtemelen kolun erisim alani disinda",
        }
    return {"success": True, "joints": result.x.tolist(), "error_m": final_error}


if __name__ == "__main__":
    # Hizli dogrulama: bilinen bir eklem konfigurasyonunun FK'sini hesapla,
    # sonra o noktayi IK ile geri coz, orijinal acilara yakin cikmali.
    test_q = (0.3, -0.2, 0.1, 0.1)
    p = forward_kinematics(*test_q)
    print(f"FK({test_q}) -> {p}")

    ik = inverse_kinematics(*p)
    print(f"IK({p}) -> {ik}")
    print(f"Beklenen ~{test_q}, bulunan {ik['joints']}")
