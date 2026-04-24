def test_mimicrec_importable():
    import mimicrec
    assert mimicrec.__version__ == "0.1.0"


def test_lerobot_api_surface_we_rely_on():
    """Fail fast if the LeRobot API we lean on in Tasks 1 and 5 has drifted.

    Tasks 1 and 5 call `LeRobotDataset.resume(repo_id=..., root=...)`. If that
    signature has changed in the editable-installed lerobot, both spike tests
    will skip with a PIVOT message and we'd miss the compatibility guarantee.
    Catch it here at Task 0 instead.
    """
    import inspect
    import pytest
    try:
        from lerobot.datasets.lerobot_dataset import LeRobotDataset
    except Exception as e:
        pytest.skip(f"lerobot not importable yet: {e}")
    assert hasattr(LeRobotDataset, "resume"), (
        "LeRobotDataset.resume has disappeared; re-check Tasks 1 and 5 spike paths."
    )
    sig = inspect.signature(LeRobotDataset.resume)
    params = set(sig.parameters.keys())
    # Allow extra params, but these two must be accepted by name.
    missing = {"repo_id", "root"} - params
    assert not missing, f"LeRobotDataset.resume missing expected params: {missing}"
