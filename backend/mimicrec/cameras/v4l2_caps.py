"""V4L2 capability enumeration via `v4l2-ctl --list-formats-ext`.

Parses the textual output of v4l2-ctl into structured capability data.
Multiplane formats and stepwise/continuous frame sizes are skipped because
cv2's V4L2 backend does not support them.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


@dataclass
class FrameSize:
    width: int
    height: int
    fps: list[int]  # discrete frame rates available at this size


@dataclass
class FormatCaps:
    fourcc: str
    description: str
    sizes: list[FrameSize]


_FMT_RE = re.compile(r"^\s*\[\d+\]:\s+'([A-Z0-9]+)'\s+\(([^)]+)\)(?:\s+\([^)]*\))?\s*$")
_SIZE_DISCRETE_RE = re.compile(r"^\s*Size:\s+Discrete\s+(\d+)x(\d+)\s*$")
_INTERVAL_DISCRETE_RE = re.compile(
    r"^\s*Interval:\s+Discrete\s+[\d.]+s\s+\(([\d.]+)\s+fps\)\s*$"
)


def parse_v4l2_listfmts(stdout: str) -> list[FormatCaps]:
    """Parse the stdout of `v4l2-ctl --list-formats-ext` for a single device.

    Only `Type: Video Capture` blocks are considered; multiplanar blocks are
    dropped. Within a kept block, only Discrete sizes and Discrete intervals
    are kept; stepwise/continuous variants are dropped.
    """
    lines = stdout.splitlines()

    in_capture_block = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "Type: Video Capture":
            in_capture_block = True
            lines = lines[i + 1 :]
            break
        if stripped.startswith("Type: Video Capture Multiplanar"):
            return []
    if not in_capture_block:
        return []

    formats: list[FormatCaps] = []
    current_fmt: FormatCaps | None = None
    current_size: FrameSize | None = None

    for line in lines:
        m = _FMT_RE.match(line)
        if m:
            current_fmt = FormatCaps(fourcc=m.group(1), description=m.group(2), sizes=[])
            formats.append(current_fmt)
            current_size = None
            continue

        m = _SIZE_DISCRETE_RE.match(line)
        if m:
            if current_fmt is None:
                continue
            current_size = FrameSize(width=int(m.group(1)), height=int(m.group(2)), fps=[])
            current_fmt.sizes.append(current_size)
            continue

        m = _INTERVAL_DISCRETE_RE.match(line)
        if m:
            if current_size is None:
                continue
            current_size.fps.append(int(round(float(m.group(1)))))
            continue

        if "Size: Stepwise" in line or "Size: Continuous" in line:
            current_size = None

    # Drop sizes with no discrete intervals, then drop formats with no surviving sizes.
    for f in formats:
        f.sizes = [s for s in f.sizes if s.fps]
    return [f for f in formats if f.sizes]


def enumerate_capabilities(device_path: str) -> list[FormatCaps]:
    """Run v4l2-ctl on the given device and return parsed capabilities.

    Returns [] if v4l2-ctl is not on PATH, returns non-zero, or output is empty.
    """
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-formats-ext", "--device", device_path],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    if result.returncode != 0:
        return []
    return parse_v4l2_listfmts(result.stdout)
