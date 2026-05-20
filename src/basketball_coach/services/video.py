import subprocess
import os
import shutil
import base64
from pathlib import Path


def _ffmpeg_exe() -> str:
    # prefer system ffmpeg if available
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    # fall back to imageio-ffmpeg bundled binary
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise RuntimeError("ffmpeg not found — install ffmpeg or imageio-ffmpeg")


def _ffprobe_exe() -> str:
    exe = shutil.which("ffprobe")
    if exe:
        return exe
    # imageio-ffmpeg puts ffprobe next to ffmpeg
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        probe = ffmpeg_path.replace("ffmpeg", "ffprobe")
        if os.path.exists(probe):
            return probe
    except Exception:
        pass
    return "ffprobe"


def extract_frames_for_range(video_path: str, start: float, end: float,
                              output_dir: str, fps: float = 1.0) -> list[str]:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    duration = max(end - start, 0.5)
    pattern = os.path.join(output_dir, "frame_%04d.jpg")
    cmd = [
        _ffmpeg_exe(), "-y",
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
    cmd = [_ffprobe_exe(), "-v", "quiet", "-print_format", "json",
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
