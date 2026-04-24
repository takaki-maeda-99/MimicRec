from __future__ import annotations
import cv2
import numpy as np


def downscale(bgr: np.ndarray, max_edge_px: int = 320) -> np.ndarray:
    h, w = bgr.shape[:2]
    scale = min(1.0, max_edge_px / max(h, w))
    if scale >= 1.0:
        return bgr
    return cv2.resize(bgr, (int(w * scale), int(h * scale)))


def encode_jpeg(bgr: np.ndarray, quality: int = 60) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("jpeg encoding failed")
    return buf.tobytes()
