from __future__ import annotations
import base64
import io
from dataclasses import dataclass, field
import numpy as np
from scipy.spatial.transform import Rotation as R
import httpx
from PIL import Image

from mimicrec.adapters.types import GripperConvention, ProprioLayout
from mimicrec.inference.contract import ContractSpec
from mimicrec.kinematics.fk import FKService
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class InferenceClient:
    spec: ContractSpec
    fk: FKService | None = None
    gripper_convention: GripperConvention | None = None
    proprio_layout: ProprioLayout | None = None
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def predict(
        self,
        frames: dict[str, Stamped[Frame]],
        state: Stamped[RobotState],
        instr: Stamped[str],
        extras: dict | None = None,
    ) -> dict:
        body = self._build_request_body(frames, state.value, instr.value, extras or {})
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.spec.endpoint.timeout_s)
        resp = await self._client.post(
            self.spec.endpoint.url,
            json=body,
            headers=self.spec.endpoint.headers,
        )
        resp.raise_for_status()
        return resp.json()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _build_request_body(self, frames, state: RobotState, instruction: str, extras: dict) -> dict:
        body: dict = {}
        for cam_name, image_spec in self.spec.request.images.items():
            stamped = frames.get(cam_name)
            if stamped is None:
                raise ValueError(
                    f"contract requires image role {cam_name!r} but frames dict "
                    f"has no entry for it"
                )
            body[image_spec.field] = self._encode_image(
                stamped.value.image, image_spec.resize, image_spec.jpeg_quality,
            )
        body[self.spec.request.state.field] = self._encode_state(state)
        body[self.spec.request.instruction.field] = instruction
        body.update(self.spec.request.extra_fields)
        body.update(extras)
        return body

    def _encode_state(self, state: RobotState) -> list[float]:
        out: list[float] = []
        T_ee: np.ndarray | None = None

        def _ensure_T() -> np.ndarray:
            nonlocal T_ee
            if T_ee is not None:
                return T_ee
            if state.ee_pos is not None and state.ee_rotvec is not None:
                T = np.eye(4)
                T[:3, 3] = state.ee_pos
                if np.linalg.norm(state.ee_rotvec) > 1e-9:
                    T[:3, :3] = R.from_rotvec(state.ee_rotvec).as_matrix()
                T_ee = T
            else:
                if self.fk is None:
                    raise ValueError(
                        "contract requires ee_pos/ee_rotvec but FKService is not wired"
                    )
                n = self.fk.n_kin_joints
                T_ee = self.fk.matrix(state.joint_pos[:n].astype(np.float64))
            return T_ee

        for comp in self.spec.request.state.components:
            if comp == "joint_pos":
                out.extend(state.joint_pos.tolist())
            elif comp == "ee_pos":
                T = _ensure_T()
                out.extend(T[:3, 3].tolist())
            elif comp == "ee_rotvec":
                T = _ensure_T()
                out.extend(R.from_matrix(T[:3, :3]).as_rotvec().tolist())
            elif comp == "gripper_pos":
                out.append(self._normalized_gripper(state))
            else:
                raise ValueError(f"unsupported state component: {comp}")
        return out

    def _normalized_gripper(self, state: RobotState) -> float:
        """Normalize raw gripper → [0,1] via convention. The source of the raw
        value is declared in ProprioLayout.

        Falls back to raw ``state.gripper_pos`` (without normalization) when
        convention/layout are not wired, preserving backward compatibility until
        the lifecycle wires them in (Task 9).
        """
        if self.gripper_convention is None or self.proprio_layout is None:
            return float(state.gripper_pos or 0.0)
        gc = self.gripper_convention
        pl = self.proprio_layout

        if pl.gripper_via_column == "observation.state.joint_pos":
            if pl.gripper_index_in_column >= state.joint_pos.shape[0]:
                raise ValueError(
                    f"gripper index {pl.gripper_index_in_column} out of range "
                    f"for joint_pos length {state.joint_pos.shape[0]}"
                )
            raw = float(state.joint_pos[pl.gripper_index_in_column])
        elif pl.gripper_via_column == "observation.state.gripper_pos":
            if state.gripper_pos is None:
                raise ValueError(
                    "contract requires gripper_pos sourced from state.gripper_pos, "
                    "but state.gripper_pos is None"
                )
            raw = float(state.gripper_pos)
        else:
            raise ValueError(
                f"unsupported gripper_via_column {pl.gripper_via_column!r}; "
                f"expected 'observation.state.joint_pos' or "
                f"'observation.state.gripper_pos'"
            )

        span = gc.open_at - gc.closed_at
        return float(np.clip((raw - gc.closed_at) / span, 0.0, 1.0))

    @staticmethod
    def _encode_image(img: np.ndarray, resize: tuple[int, int], jpeg_quality: int) -> str:
        # Frame.image is HxWx3 uint8 BGR (per types.py:70). PIL expects RGB; we
        # must swap channels before encoding, or the VLA server sees R<->B inverted.
        # `img[..., ::-1]` is a view; copy() to ensure C-contiguous for PIL.
        rgb = img[..., ::-1].copy()
        pil = Image.fromarray(rgb)
        if pil.size != tuple(resize):
            pil = pil.resize(tuple(resize))
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=jpeg_quality)
        return base64.b64encode(buf.getvalue()).decode("ascii")
