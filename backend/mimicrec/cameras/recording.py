from __future__ import annotations
from pathlib import Path

import av
import numpy as np


class Mp4EpisodeWriter:
    def __init__(self, path: Path, fps: int, width: int, height: int):
        self._path = path
        self._container = av.open(str(path), mode="w")
        self._stream = self._container.add_stream("libx264", rate=fps)
        self._stream.width = width
        self._stream.height = height
        self._stream.pix_fmt = "yuv420p"
        self._frame_index = 0

    def write_frame(self, bgr: np.ndarray) -> int:
        vf = av.VideoFrame.from_ndarray(bgr, format="bgr24").reformat(format="yuv420p")
        packet = self._stream.encode(vf)
        if packet:
            for p in packet:
                self._container.mux(p)
        idx = self._frame_index
        self._frame_index += 1
        return idx

    def close(self) -> None:
        for p in self._stream.encode():
            self._container.mux(p)
        self._container.close()
