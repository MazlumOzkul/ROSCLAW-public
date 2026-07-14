"""
ROSClaw - turtlebot3_manipulation'i Gazebo Sim'de (ros_gz) baslatir.

ROBOTIS'in resmi paketi klasik Gazebo hedefledigi icin, bu klasordeki
kendi portumuz kullanilir (turtlebot3_manipulation.urdf.xacro + gz-native
sensor/aktuator xacro'lari). Referans deseni: ros-jazzy-gz-ros2-control-demos
paketindeki diff_drive_example.launch.py (bu ortamda dogrulanmis calisan
gz_sim + ros_gz_sim create + controller_manager spawner sirasi).

Calistirma: ros2 launch /root/rosclaw_sim/manipulation_sim.launch.py
"""
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

SIM_DIR = "/root/rosclaw_sim"


def generate_launch_description():
    robot_description_content = Command([
        PathJoinSubstitution([FindExecutable(name="xacro")]),
        " ",
        f"{SIM_DIR}/turtlebot3_manipulation.urdf.xacro",
    ])
    robot_description = {
        "robot_description": ParameterValue(robot_description_content, value_type=str)
    }

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[robot_description, {"use_sim_time": True}],
    )

    gz_sim = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare("ros_gz_sim"), "launch", "gz_sim.launch.py"
            ])
        ),
        launch_arguments=[("gz_args", f" -r -v 1 {SIM_DIR}/rosclaw_world.sdf")],
    )

    gz_spawn_entity = Node(
        package="ros_gz_sim",
        executable="create",
        output="screen",
        arguments=["-topic", "robot_description", "-name", "turtlebot3_manipulation",
                   "-allow_renaming", "true", "-x", "-1.5", "-y", "0.0", "-z", "0.05"],
    )

    bridge = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[f"--ros-args", "-p", f"config_file:={SIM_DIR}/bridge.yaml"],
        output="screen",
    )

    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster"],
    )
    arm_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["arm_controller"],
    )
    gripper_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["gripper_controller"],
    )

    return LaunchDescription([
        gz_sim,
        robot_state_publisher,
        bridge,
        gz_spawn_entity,
        RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=gz_spawn_entity,
                on_exit=[joint_state_broadcaster_spawner],
            )
        ),
        RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=joint_state_broadcaster_spawner,
                on_exit=[arm_controller_spawner],
            )
        ),
        RegisterEventHandler(
            event_handler=OnProcessExit(
                target_action=arm_controller_spawner,
                on_exit=[gripper_controller_spawner],
            )
        ),
    ])
