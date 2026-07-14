#!/usr/bin/env python3
"""
ROSClaw - turtlebot3_manipulation icin move_group baslatici.

Vendor'un kendi move_group.launch.py'si ve config/ompl_planning.yaml dosyasi
birden fazla soruna sahip (Humble-donemi param semasi + eksik/yanlis
doldurulmus sablon):
  1. 'request_adapters' yanlislikla tek string'di, gercek liste degildi.
  2. ompl_planning.yaml'da 'planning_plugin' anahtari hic yoktu.
  3. ompl_planning.yaml hala Franka Panda ORNEK sablonundan kalma grup
     isimlerini iceriyordu (panda_arm, panda_arm_hand, hand) - bizim
     GERCEK gruplarimiz (arm, gripper) icin hic planner_configs yoktu.
  4. pilz_cartesian_limits.yaml hic yok (Pilz planlayicisi dahil edilmemis).

Cozum: resmi MoveItConfigsBuilder'i kullan (dogru modern sema icin), sadece
OMPL pipeline'ini yukle (Pilz'i atla), sonra donen planning_pipelines
dict'ini elle yamalayarak eksik/yanlis kisimlari duzelt.
"""
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launches import generate_move_group_launch

SIM_DIR = "/root/rosclaw_sim"

# Vendor'un ompl_planning.yaml'indaki TUM planner konfigurasyon isimleri -
# arm ve gripper gruplarimiz icin de ayni varsayilan listeyi kullanacagiz.
_ALL_PLANNER_CONFIGS = [
    "SBLkConfigDefault", "ESTkConfigDefault", "LBKPIECEkConfigDefault",
    "BKPIECEkConfigDefault", "KPIECEkConfigDefault", "RRTkConfigDefault",
    "RRTConnectkConfigDefault", "RRTstarkConfigDefault", "TRRTkConfigDefault",
    "PRMkConfigDefault", "PRMstarkConfigDefault", "FMTkConfigDefault",
    "BFMTkConfigDefault", "PDSTkConfigDefault", "STRIDEkConfigDefault",
    "BiTRRTkConfigDefault", "LBTRRTkConfigDefault", "BiESTkConfigDefault",
    "ProjESTkConfigDefault", "LazyPRMkConfigDefault", "LazyPRMstarkConfigDefault",
    "SPARSkConfigDefault", "SPARStwokConfigDefault", "TrajOptDefault",
]


def generate_launch_description():
    moveit_config = (
        MoveItConfigsBuilder("turtlebot3_manipulation", package_name="turtlebot3_manipulation_moveit_config")
        .robot_description(file_path=f"{SIM_DIR}/turtlebot3_manipulation.urdf.xacro")
        .planning_pipelines(default_planning_pipeline="ompl", pipelines=["ompl"])
        .to_moveit_configs()
    )

    # --- Yama: eksik/yanlis kisimlari duzelt ---
    ompl_cfg = moveit_config.planning_pipelines["ompl"]
    ompl_cfg["planning_plugin"] = "ompl_interface/OMPLPlanner"
    ompl_cfg["request_adapters"] = [
        "default_planner_request_adapters/AddTimeOptimalParameterization",
        "default_planner_request_adapters/FixWorkspaceBounds",
        "default_planner_request_adapters/FixStartStateBounds",
        "default_planner_request_adapters/FixStartStateCollision",
        "default_planner_request_adapters/FixStartStatePathConstraints",
    ]
    ompl_cfg["start_state_max_bounds_error"] = 0.1

    # Panda sablonundan kalma grup adlarini temizle, GERCEK gruplarimiza
    # (arm, gripper) planner_configs ata.
    for stale_group in ("panda_arm", "panda_arm_hand", "hand"):
        ompl_cfg.pop(stale_group, None)
    ompl_cfg["arm"] = {"planner_configs": list(_ALL_PLANNER_CONFIGS)}
    ompl_cfg["gripper"] = {"planner_configs": list(_ALL_PLANNER_CONFIGS)}

    return generate_move_group_launch(moveit_config)
