"""Subtask annotation — currently a MOCK pending MimicAno integration.

The real subtask prediction pipeline lives in MimicAno/ (see
MimicAno/docs/design.md). This module stubs out `annotate_episode` so the
existing API/UI keeps working while MimicAno is being built. Helper
functions (_extract_frames, _select_keyframes, _build_prompt, _parse_response)
are kept as reference for the eventual real implementation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk

if TYPE_CHECKING:
    from mimicrec.cloud.push_state import PushCoordinator

logger = logging.getLogger(__name__)


@dataclass
class SubtaskSegment:
    name: str
    start_frame: int
    end_frame: int
    description: str = ""


def _extract_frames(video_path: Path, sample_fps: float = 1.0) -> list[tuple[int, np.ndarray]]:
    """Extract frames from MP4 at the given sample rate."""
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    step = max(1, int(fps / sample_fps))

    frames = []
    for i in range(0, total, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            if max(h, w) > 512:
                scale = 512 / max(h, w)
                rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
            frames.append((i, rgb))
    cap.release()
    return frames


def _select_keyframes(frames: list[tuple[int, np.ndarray]], max_frames: int = 8) -> list[tuple[int, np.ndarray]]:
    """Select keyframes based on visual change — like a storyboard.

    Always includes first and last frame. Remaining slots go to frames
    with the largest visual difference from their predecessor.
    """
    if len(frames) <= max_frames:
        return frames

    # Compute frame-to-frame difference scores
    diffs = []
    for i in range(1, len(frames)):
        prev = frames[i - 1][1].astype(np.float32)
        curr = frames[i][1].astype(np.float32)
        # Resize to same small size for fast comparison
        prev_small = cv2.resize(prev, (64, 64))
        curr_small = cv2.resize(curr, (64, 64))
        diff = np.mean(np.abs(curr_small - prev_small))
        diffs.append((i, diff))

    # Sort by difference (largest change first)
    diffs.sort(key=lambda x: x[1], reverse=True)

    # Always include first and last
    selected_indices = {0, len(frames) - 1}

    # Fill remaining slots with highest-change frames
    for idx, _ in diffs:
        if len(selected_indices) >= max_frames:
            break
        selected_indices.add(idx)

    # Return in original order
    return [frames[i] for i in sorted(selected_indices)]


def _build_prompt(num_frames: int) -> str:
    return f"""You are analyzing a robot manipulation episode recorded as a sequence of {num_frames} camera images.

Divide this episode into sequential subtasks. Each subtask should be a distinct phase of the manipulation (e.g., "approach object", "grasp", "lift", "move to target", "place", "release", "retract").

Respond with a JSON array of subtasks. Each subtask has:
- "name": short name (2-4 words)
- "start_image": 0-indexed image number where this subtask begins
- "end_image": 0-indexed image number where this subtask ends (inclusive)
- "description": one sentence describing what happens

Example:
[
  {{"name": "approach object", "start_image": 0, "end_image": 3, "description": "Robot arm moves toward the target object"}},
  {{"name": "grasp", "start_image": 4, "end_image": 5, "description": "Gripper closes around the object"}}
]

Return ONLY the JSON array, no other text."""


def annotate_episode(
    ds_root: Path,
    episode_idx: int,
    camera_name: str = "front",
    model_name: str = "mock",
    sample_fps: float = 1.0,
    device: str = "cpu",
    custom_prompt: str | None = None,
) -> list[SubtaskSegment]:
    """MOCK subtask annotator.

    Returns deterministic placeholder subtask segments based on the episode's
    frame count. Real subtask prediction will live in the MimicAno package
    (see MimicAno/docs/design.md). This stub keeps the existing API + UI
    working until that lands.

    The signature is stable so callers don't need to change when the real
    implementation is wired in.
    """
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)

    # Verify the video and parquet exist so callers see a real error if the
    # episode is missing rather than a phantom annotation.
    video_path = paths.episode_video(chunk, camera_name, episode_idx)
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    pq_path = paths.episode_parquet(chunk, episode_idx)
    table = pq.read_table(pq_path)
    total_frames = table.num_rows

    logger.info(
        f"[mock annotator] episode {episode_idx}: {total_frames} frames "
        f"(camera={camera_name}). Real impl pending in MimicAno."
    )

    # Three even thirds: approach / interact / retract.
    if total_frames < 3:
        return [
            SubtaskSegment(
                name="placeholder",
                start_frame=0,
                end_frame=max(0, total_frames - 1),
                description="mock segment (MimicAno will replace this)",
            )
        ]

    a = total_frames // 3
    b = (2 * total_frames) // 3
    return [
        SubtaskSegment(name="approach", start_frame=0, end_frame=a - 1,
                       description="mock segment (MimicAno will replace this)"),
        SubtaskSegment(name="interact", start_frame=a, end_frame=b - 1,
                       description="mock segment (MimicAno will replace this)"),
        SubtaskSegment(name="retract", start_frame=b, end_frame=total_frames - 1,
                       description="mock segment (MimicAno will replace this)"),
    ]


def release_vlm() -> None:
    """No-op in mock mode; kept for API compatibility."""
    return


def _parse_response(
    response: str,
    sampled: list[tuple[int, np.ndarray]],
    total_frames: int,
    fps: float,
    sample_fps: float,
) -> list[SubtaskSegment]:
    """Parse VLM response into SubtaskSegments with actual frame indices."""
    # Extract JSON from response
    text = response.strip()
    # Find JSON array
    start = text.find("[")
    end = text.rfind("]") + 1
    if start < 0 or end <= start:
        logger.warning(f"No JSON array found in response: {text[:100]}")
        return [SubtaskSegment(name="full_episode", start_frame=0, end_frame=total_frames - 1)]

    try:
        items = json.loads(text[start:end])
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse JSON: {text[start:end][:100]}")
        return [SubtaskSegment(name="full_episode", start_frame=0, end_frame=total_frames - 1)]

    # Map image indices back to actual frame indices
    segments = []
    for item in items:
        img_start = item.get("start_image", 0)
        img_end = item.get("end_image", len(sampled) - 1)

        # Clamp to valid range
        img_start = max(0, min(img_start, len(sampled) - 1))
        img_end = max(img_start, min(img_end, len(sampled) - 1))

        # Map to actual frame indices
        frame_start = sampled[img_start][0] if img_start < len(sampled) else 0
        frame_end = sampled[img_end][0] if img_end < len(sampled) else total_frames - 1

        segments.append(SubtaskSegment(
            name=item.get("name", f"subtask_{len(segments)}"),
            start_frame=frame_start,
            end_frame=frame_end,
            description=item.get("description", ""),
        ))

    return segments


def _save_annotations_inner(
    ds_root: Path,
    episode_index: int,
    segments: list[SubtaskSegment],
) -> None:
    """Core implementation of save_annotations (no locking)."""
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_index)
    pq_path = paths.episode_parquet(chunk, episode_index)

    table = pq.read_table(pq_path)
    rows = table.to_pylist()

    # Assign subtask_index and subtask_name to each frame
    for row in rows:
        frame_idx = row.get("frame_index", 0)
        subtask_idx = 0
        subtask_name = "unknown"
        for i, seg in enumerate(segments):
            if seg.start_frame <= frame_idx <= seg.end_frame:
                subtask_idx = i
                subtask_name = seg.name
                break
        row["subtask_index"] = subtask_idx
        row["subtask_name"] = subtask_name

    import pyarrow as pa
    from mimicrec.recording.atomic_io import _atomic_write_parquet
    new_table = pa.Table.from_pylist(rows)
    _atomic_write_parquet(new_table, pq_path)
    logger.info(f"Saved {len(segments)} subtask annotations to {pq_path}")


def save_annotations(
    ds_root: Path,
    episode_index: int,
    segments: list[SubtaskSegment],
    *,
    coordinator: "PushCoordinator | None" = None,
    ds_name: str | None = None,
) -> None:
    """Save subtask annotations back to the episode parquet."""
    if coordinator is not None and ds_name is not None:
        lock = coordinator.get_save_lock(ds_name)
        with lock:
            _save_annotations_inner(ds_root, episode_index, segments)
    else:
        _save_annotations_inner(ds_root, episode_index, segments)
