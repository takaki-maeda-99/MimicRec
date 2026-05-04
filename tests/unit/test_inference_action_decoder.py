import numpy as np
import pytest

from mimicrec.inference.action_decoder import ActionDecoder
from mimicrec.inference.contract import ContractSpec
from mimicrec.types import RobotState


YAML_CONTRACT = """
name: test
endpoint:
  url: http://x:1/p
  method: POST
  retry: { max_attempts: 0 }
request:
  images: { front: { field: img, encoding: jpeg_base64, resize: [224,224], jpeg_quality: 90 } }
  state:  { field: proprio, components: [joint_pos, gripper_pos], normalization: { method: none } }
  instruction: { field: instr }
response:
  actions_path: actions
  chunk: { expected_size: 4, on_size_mismatch: use_actual }
  action:
    type: ee_delta
    frame: ee_local
    pose: { units: meter_axisangle_rad }
    gripper: { kind: absolute, units: normalized_0_1 }
    components: [ee_delta, gripper]
    normalization: { method: none }
loop:
  prefetch_threshold: 0.5
  max_inflight: 1
"""


def _state(joint_pos=None) -> RobotState:
    if joint_pos is None:
        joint_pos = np.array([0.0, 0.0, 0.0, 0.0, 0.0])
    return RobotState(
        joint_pos=np.asarray(joint_pos, dtype=np.float64),
        joint_vel=np.zeros_like(joint_pos),
        joint_effort=np.zeros_like(joint_pos),
        gripper_pos=0.0,
        t_mono_ns=0,
    )


class FakeIK:
    def __init__(self):
        self.calls = []
    def solve(self, T, seed):
        # Round-trip: assume FK followed by IK returns the seed plus a small bias.
        self.calls.append((T.copy(), seed.copy()))
        return seed + 0.01, True


class FakeFK:
    def matrix(self, q):
        # Identity matrix as a stand-in
        T = np.eye(4)
        T[:3, 3] = q[:3] * 0.001
        return T


def test_decode_zero_delta_chunk_round_trips():
    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5, action_stats=None)
    raw = {"actions": [
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
    ]}
    chunk = dec.decode(raw, current_state=_state())
    assert len(chunk) == 2
    assert chunk[0].gripper == 0.5
    assert chunk[0].ik_failed is False


def test_decode_mean_std_de_normalization():
    """Critical safety test: de-normalize must apply BEFORE building T_delta.
    Without this, a normalized 1.0 from the VLA gets treated as 1.0 m of motion.
    With mean=0, std=0.001, a normalized 1.0 should map to 0.001 m (1 mm)."""
    import yaml as _yaml
    d = _yaml.safe_load(YAML_CONTRACT)
    d["response"]["action"]["normalization"] = {"method": "mean_std"}
    spec = ContractSpec.from_yaml_text(_yaml.safe_dump(d))

    # mean=0, std=0.001 (typical SO-101-scale stats); 7-dim ee_delta + gripper
    stats = {"mean": [0.0]*7, "std": [0.001]*7}

    captured_T = []
    class CaptureIK:
        def solve(self, T, seed):
            captured_T.append(T.copy())
            return seed.copy(), True

    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=CaptureIK(), narm=5, action_stats=stats)
    # Send a normalized action with x=+1.0 (i.e. +1 std away from mean).
    # Expected physical x = 0 + 1.0 * 0.001 = 0.001 m, NOT 1.0 m.
    raw = {"actions": [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]]}
    dec.decode(raw, current_state=_state())
    # FakeFK returns identity, so T_curr = I, T_next = I @ T_delta = T_delta.
    # Position component must equal de-normalized 0.001, not raw 1.0.
    assert abs(captured_T[0][0, 3] - 0.001) < 1e-9, \
        f"de-normalize FAILED: expected 0.001 m, got {captured_T[0][0,3]} m"


def test_decode_minmax_neg1_pos1_de_normalization():
    """method=minmax_neg1_pos1: arr in [-1, +1] -> physical [low, high].
    mean=0.0 represents the midpoint, std doubles as half-range."""
    import yaml as _yaml
    d = _yaml.safe_load(YAML_CONTRACT)
    d["response"]["action"]["normalization"] = {"method": "minmax_neg1_pos1"}
    spec = ContractSpec.from_yaml_text(_yaml.safe_dump(d))
    # Convention: stats hold mean & std where physical = mean + arr * std (so for
    # minmax-+-1, std == half-range and mean == midpoint). MVP keeps this single
    # interpretation; alternative scalings can be added later via stats_ref.
    stats = {"mean": [0.0]*7, "std": [0.005]*7}

    captured_T = []
    class CaptureIK:
        def solve(self, T, seed):
            captured_T.append(T.copy())
            return seed.copy(), True

    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=CaptureIK(), narm=5, action_stats=stats)
    raw = {"actions": [[-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]]}  # min of range
    dec.decode(raw, current_state=_state())
    assert abs(captured_T[0][0, 3] - (-0.005)) < 1e-9


def test_decode_unknown_normalization_method_raises():
    import yaml as _yaml
    d = _yaml.safe_load(YAML_CONTRACT)
    d["response"]["action"]["normalization"] = {"method": "none"}
    spec = ContractSpec.from_yaml_text(_yaml.safe_dump(d))
    # Patch in an invalid method post-load to test decoder hardening.
    spec.response.action.normalization.method = "magic"  # type: ignore
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5, action_stats=None)
    with pytest.raises(ValueError, match="normalization"):
        dec.decode({"actions": [[0.0]*7]}, current_state=_state())
