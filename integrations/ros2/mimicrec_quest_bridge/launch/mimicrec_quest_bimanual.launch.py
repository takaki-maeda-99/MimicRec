from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    config_dir = Path(get_package_share_directory("mimicrec_quest_bridge")) / "config"
    return LaunchDescription([
        DeclareLaunchArgument("right_config", default_value=str(config_dir / "quest3.yaml")),
        DeclareLaunchArgument("left_config", default_value=str(config_dir / "quest3_left.yaml")),
        DeclareLaunchArgument("run_endpoint", default_value="true"),
        DeclareLaunchArgument("endpoint_host", default_value="0.0.0.0"),
        DeclareLaunchArgument("endpoint_port", default_value="10000"),
        Node(
            package="ros_tcp_endpoint",
            executable="default_server_endpoint",
            name="unity_ros_tcp_endpoint",
            output="screen",
            condition=IfCondition(LaunchConfiguration("run_endpoint")),
            parameters=[{
                "ROS_IP": LaunchConfiguration("endpoint_host"),
                "ROS_TCP_PORT": ParameterValue(
                    LaunchConfiguration("endpoint_port"), value_type=int
                ),
            }],
        ),
        Node(
            package="mimicrec_quest_bridge",
            executable="mimicrec_quest_bridge",
            name="mimicrec_quest_bridge",
            output="screen",
            parameters=[LaunchConfiguration("right_config")],
        ),
        Node(
            package="mimicrec_quest_bridge",
            executable="mimicrec_quest_bridge",
            name="mimicrec_quest_bridge_left",
            output="screen",
            parameters=[LaunchConfiguration("left_config")],
        ),
    ])
