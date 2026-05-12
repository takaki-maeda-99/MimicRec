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


def test_gripper_binary_kind():
    yaml_bin = YAML_CONTRACT.replace("kind: absolute", "kind: binary").replace(
        "units: normalized_0_1", "units: binary_threshold_0p5",
    )
    spec = ContractSpec.from_yaml_text(yaml_bin)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5, action_stats=None)
    raw = {"actions": [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.7]]}
    chunk = dec.decode(raw, current_state=_state())
    assert chunk[0].gripper == 1.0


def test_gripper_delta_kind_accumulates():
    yaml_delta = YAML_CONTRACT.replace("kind: absolute", "kind: delta")
    spec = ContractSpec.from_yaml_text(yaml_delta)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5, action_stats=None)
    raw = {"actions": [[0.0]*6 + [0.1]]}
    state = RobotState(
        joint_pos=np.array([0.0, 0.0, 0.0, 0.0, 0.0]),
        joint_vel=np.zeros(5),
        joint_effort=np.zeros(5),
        gripper_pos=0.4,
        t_mono_ns=0,
    )
    chunk = dec.decode(raw, current_state=state)
    assert chunk[0].gripper == pytest.approx(0.5)


def test_ik_failure_falls_back_to_seed():
    class FailingIK:
        def solve(self, T, seed):
            return seed.copy(), False
    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FailingIK(), narm=5, action_stats=None)
    raw = {"actions": [[0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5]]}
    chunk = dec.decode(raw, current_state=_state(joint_pos=np.full(5, 7.0)))
    assert chunk[0].ik_failed
    assert np.allclose(chunk[0].q, 7.0)
    # IK failure path is independent of normalization; either contract works.


def test_ik_failure_does_not_drift_t_curr():
    """When IK fails on step k, T_curr must revert to FK(seed) so step k+1
    chains from the actual achievable pose, not from the unreachable T_next.
    Without this, repeated IK failures compound drift and later steps target
    poses far from the physical seed."""
    fk_calls: list[np.ndarray] = []

    class CountingFK:
        def matrix(self, q):
            fk_calls.append(np.asarray(q).copy())
            T = np.eye(4)
            T[:3, 3] = q[:3] * 0.001  # arbitrary deterministic mapping
            return T

    captured_T_for_ik: list[np.ndarray] = []

    class TFailIK:
        """Fails on step 0 (so T_curr would otherwise advance to T_next), then
        succeeds on step 1 — we observe what T was passed to IK on step 1."""
        def __init__(self):
            self.calls = 0

        def solve(self, T, seed):
            self.calls += 1
            captured_T_for_ik.append(T.copy())
            if self.calls == 1:
                return seed.copy(), False  # IK fail
            return seed.copy(), True

    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=CountingFK(), ik=TFailIK(), narm=5, action_stats=None)
    raw = {"actions": [
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
        [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.5],
    ]}
    seed = np.full(5, 7.0)
    dec.decode(raw, current_state=_state(joint_pos=seed))

    # On step 0 we fail. The fix: T_curr must revert to FK(seed), so on
    # step 1 we pass T = FK(seed) @ T_delta (ee_local frame), NOT
    # captured_T_for_ik[0] @ T_delta which would compound the failed delta.
    assert any(np.array_equal(c, seed) for c in fk_calls[1:]), \
        "After IK failure, FK(seed) must be re-evaluated to revert T_curr"

    # Stronger assertion: verify the actual T_target passed to IK on step 1.
    # FakeFK.matrix(q) returns translation(q[:3] * 0.001). With seed=[7,7,7,7,7],
    # FK(seed)[:3,3] = [0.007, 0.007, 0.007]. T_delta is translation(1.0, 0, 0)
    # (arr[0] = 1.0). So under the FIX, captured_T_for_ik[1][:3,3] should be
    # FK(seed) @ T_delta = [0.007 + 1.0, 0.007, 0.007] = [1.007, ...].
    # Under the BUG (T_curr advanced to T_next on failure), step 1 would have
    # T_curr[:3,3] = [1.007, ...] and step 1 T_next would compound to
    # [2.007, ...]. Asserting against the correct value distinguishes them.
    step1_T = captured_T_for_ik[1]
    assert step1_T[0, 3] == pytest.approx(1.007, abs=1e-9), \
        f"step 1 T_target.x should be 1.007 (FK(seed)+delta), got {step1_T[0, 3]:.6f} " \
        f"— the bug case would produce ~2.007 (compounded from failed step)"


def test_decode_rejects_wrong_row_length():
    spec = ContractSpec.from_yaml_text(YAML_CONTRACT)
    dec = ActionDecoder(spec=spec, fk=FakeFK(), ik=FakeIK(), narm=5, action_stats=None)

    state = _state()
    bad = {"actions": [[0.0] * 6]}  # 6 floats instead of 7 (missing gripper)

    with pytest.raises(ValueError, match="action row length 6 != expected 7"):
        dec.decode(bad, state)
