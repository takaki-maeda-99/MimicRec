import pytest

# These tests need an `app` fixture that wires a SessionManager around mock_robot.
# That fixture lands in Task 26 (tests/conftest.py). Until then, skip cleanly so CI shows the deferred status.


def test_get_configs_inference_lists():
    pytest.skip("complete after Task 26 (app fixture in conftest.py)")


def test_post_start_returns_session_id():
    pytest.skip("complete after Task 26")


def test_put_instruction_409_during_recording():
    pytest.skip("complete after Task 26")
