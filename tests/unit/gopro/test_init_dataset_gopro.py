import json
from pathlib import Path

from mimicrec.gopro.types import GoProSpec
from mimicrec.recording.dataset_layout import init_dataset


def test_writes_gopro_features(tmp_path: Path):
    # init_dataset requires ds_root NOT to pre-exist (mkdir exist_ok=False).
    # pytest's tmp_path already exists, so use a sub-path.
    ds_root = tmp_path / "ds"
    init_dataset(
        ds_root=ds_root, fps=30,
        joint_names=["j0", "j1"],
        camera_names=["wrist"],
        camera_resolutions={"wrist": (640, 480)},
        gopro_specs={"gopro_x": GoProSpec(
            name="gopro_x", width=1280, height=720, fps=30, codec="libx264")},
    )
    info = json.loads((ds_root / "meta" / "info.json").read_text())
    feats = info["features"]
    assert "observation.images.wrist" in feats
    assert "observation.images.gopro_x" in feats
    g = feats["observation.images.gopro_x"]
    assert g["shape"] == [720, 1280, 3]
    assert g["info"]["video.codec"] == "libx264"
    assert g["info"]["video.fps"] == 30
    assert g["info"]["has_gpmf"] is True


def test_no_gopros_unchanged(tmp_path: Path):
    ds_root = tmp_path / "ds"
    init_dataset(
        ds_root=ds_root, fps=30,
        joint_names=["j0"],
        camera_names=["front"],
        camera_resolutions={"front": (640, 480)},
    )
    info = json.loads((ds_root / "meta" / "info.json").read_text())
    assert "observation.images.front" in info["features"]
