import subprocess
import os
import base64
from pathlib import Path


def extract_frames_for_range(video_path: str, start: float, end: float,
                              output_dir: str, fps: float = 1.0) -> list[str]:
    """Extract frames from a specific time range of a video."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    duration = max(end - start, 0.5)
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", video_path,
        "-t", str(duration),
        "-vf", f"fps={fps}",
        "-q:v", "3",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr[-400:]}")
    frames = sorted(Path(output_dir).glob("frame_*.jpg"))
    return [str(f) for f in frames]


def get_video_duration(video_path: str) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
           "-show_format", video_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return 0.0
    import json
    data = json.loads(result.stdout)
    return float(data.get("format", {}).get("duration", 0))


def frames_to_base64(frame_paths: list[str]) -> list[str]:
    out = []
    for p in frame_paths:
        try:
            with open(p, "rb") as f:
                out.append(base64.standard_b64encode(f.read()).decode())
        except Exception:
            pass
    return out
