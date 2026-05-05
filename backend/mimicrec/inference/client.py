from __future__ import annotations
import base64
import io
from dataclasses import dataclass
import numpy as np
import httpx
from PIL import Image

from mimicrec.inference.contract import ContractSpec
from mimicrec.types import Frame, RobotState, Stamped


@dataclass
class InferenceClient:
    spec: ContractSpec
    _client: httpx.AsyncClient | None = None

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
        # Images
        for cam_name, image_spec in self.spec.request.images.items():
            stamped = frames.get(cam_name)
            if stamped is None:
                continue
            img = stamped.value.image
            body[image_spec.field] = self._encode_image(img, image_spec.resize, image_spec.jpeg_quality)
        # State
        state_components = self.spec.request.state.components
        state_vec: list[float] = []
        for comp in state_components:
            if comp == "joint_pos":
                state_vec.extend(state.joint_pos.tolist())
            elif comp == "gripper_pos":
                state_vec.append(float(state.gripper_pos or 0.0))
            else:
                raise ValueError(f"unsupported state component: {comp}")
        body[self.spec.request.state.field] = state_vec
        # Instruction
        body[self.spec.request.instruction.field] = instruction
        # Extras
        body.update(self.spec.request.extra_fields)
        body.update(extras)
        return body

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
