"""Subtask annotation using Gemma 4 VLM.

Takes a recorded episode's camera frames, samples them at ~1fps,
sends to Gemma 4 vision model, and returns subtask boundaries.

Usage:
    from mimicrec.annotator.subtask import annotate_episode
    result = annotate_episode(ds_root, episode_idx, model_name="google/gemma-4-E4B")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

from mimicrec.recording.dataset_layout import dataset_paths, resolve_chunk

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
            # Convert BGR to RGB, resize for VLM
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            if max(h, w) > 512:
                scale = 512 / max(h, w)
                rgb = cv2.resize(rgb, (int(w * scale), int(h * scale)))
            frames.append((i, rgb))
    cap.release()
    return frames


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
    model_name: str = "google/gemma-4-E2B-it",
    sample_fps: float = 1.0,
    device: str = "cpu",
    custom_prompt: str | None = None,
) -> list[SubtaskSegment]:
    """Annotate an episode with subtask labels using Gemma 4 VLM.

    Args:
        ds_root: Dataset root path
        episode_idx: Episode index
        camera_name: Which camera to use for annotation
        model_name: HuggingFace model name
        sample_fps: How many frames per second to sample (1.0 = one per second)
        device: "cuda" or "cpu"

    Returns:
        List of SubtaskSegment with frame ranges
    """
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)

    # Find video file
    video_path = paths.episode_video(chunk, camera_name, episode_idx)
    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    # Read episode parquet for total frame count
    pq_path = paths.episode_parquet(chunk, episode_idx)
    table = pq.read_table(pq_path)
    total_frames = table.num_rows
    fps = 30.0  # default

    logger.info(f"Annotating episode {episode_idx}: {total_frames} frames, camera={camera_name}")

    # Extract sample frames
    sampled = _extract_frames(video_path, sample_fps=sample_fps)
    if not sampled:
        raise RuntimeError("no frames extracted")
    logger.info(f"Sampled {len(sampled)} frames from video")

    # Load model
    from transformers import AutoProcessor, AutoModelForImageTextToText
    import torch
    from PIL import Image

    logger.info(f"Loading {model_name} on {device}...")
    processor = AutoProcessor.from_pretrained(model_name)
    dtype = torch.bfloat16 if device != "cpu" else torch.float32
    model = AutoModelForImageTextToText.from_pretrained(
        model_name, torch_dtype=dtype, device_map=device
    )

    # Build prompt with images
    prompt = custom_prompt if custom_prompt else _build_prompt(len(sampled))
    images = [Image.fromarray(frame) for _, frame in sampled]

    # Create conversation format for Gemma 4
    image_tokens = "\n".join([f"<start_of_image>" for _ in images])
    full_prompt = f"{image_tokens}\n\n{prompt}"

    inputs = processor(
        text=full_prompt,
        images=images,
        return_tensors="pt",
    )
    # Move inputs to the same device as the model (handles device_map="auto")
    target_device = next(model.parameters()).device
    inputs = inputs.to(target_device)

    # Generate
    logger.info("Running inference...")
    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=1024,
            temperature=0.1,
            do_sample=False,
        )

    # Decode
    response = processor.decode(output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    logger.info(f"VLM response: {response[:200]}...")

    # Parse JSON from response
    segments = _parse_response(response, sampled, total_frames, fps, sample_fps)

    # Cleanup GPU
    del model, processor
    if device == "cuda":
        torch.cuda.empty_cache()

    return segments


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


def save_annotations(
    ds_root: Path,
    episode_idx: int,
    segments: list[SubtaskSegment],
) -> None:
    """Save subtask annotations back to the episode parquet."""
    paths = dataset_paths(ds_root)
    chunk = resolve_chunk(episode_idx)
    pq_path = paths.episode_parquet(chunk, episode_idx)

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
    new_table = pa.Table.from_pylist(rows)
    pq.write_table(new_table, pq_path)
    logger.info(f"Saved {len(segments)} subtask annotations to {pq_path}")
