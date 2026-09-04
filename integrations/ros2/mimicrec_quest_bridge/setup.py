from glob import glob
from setuptools import find_packages, setup


package_name = "mimicrec_quest_bridge"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(),
    data_files=[
        ("share/ament_index/resource_index/packages", [f"resource/{package_name}"]),
        (f"share/{package_name}", ["package.xml"]),
        (f"share/{package_name}/config", glob("config/*.yaml")),
        (f"share/{package_name}/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "websockets>=9.1"],
    zip_safe=True,
    description="Meta Quest ROS 2 teleoperation and camera bridge for MimicRec",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "mimicrec_quest_bridge = mimicrec_quest_bridge.node:main",
        ],
    },
)
