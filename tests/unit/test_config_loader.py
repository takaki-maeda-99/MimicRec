from pathlib import Path
import pytest

from mimicrec.config.loader import load_session_config


REPO_ROOT = Path(__file__).resolve().parents[2]   # MimicRec/
CONFIGS = REPO_ROOT / "configs"


def test_defaults_composition_expands_robot_and_cameras():
    cfg = load_session_config(
        CONFIGS / "sessions" / "mock_teleop.yaml",
        configs_root=CONFIGS,
    )
    assert cfg.robot._target_ == "mimicrec.adapters.mock_robot.MockRobotAdapter"
    assert cfg.teleop._target_ == "mimicrec.adapters.mock_teleop.MockTeleoperator"
    assert cfg.mapper._target_ == "mimicrec.mappers.identity.IdentityMapper"
    assert "mock_cam" in cfg.cameras
    assert cfg.recording.fps == 30
    assert cfg.task.name == "mock_pick"


def test_missing_referenced_file_raises_clear_error(tmp_path: Path):
    configs_root = tmp_path / "configs"
    (configs_root / "robots").mkdir(parents=True)
    (configs_root / "sessions").mkdir(parents=True)
    session = configs_root / "sessions" / "bad.yaml"
    session.write_text("defaults:\n  robot: doesnotexist\n")
    with pytest.raises(FileNotFoundError) as e:
        load_session_config(session, configs_root=configs_root)
    assert "doesnotexist" in str(e.value)
