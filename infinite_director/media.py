"""FFmpeg media operations. All invocation uses argv, never a shell."""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from pathlib import Path


def run(argv, timeout=600):
    try:
        result = subprocess.run([str(x) for x in argv], capture_output=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Install {argv[0]} and put it on the ComfyUI process PATH") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-3000:])
    return result.stdout


def probe(path):
    info = json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    duration = float(info.get("format", {}).get("duration", 0))
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Media must have a finite positive duration")
    return {"duration": duration, "video": video, "audio": audio}


def prepare_source(path, folder):
    meta = probe(path)
    if not meta["video"] or not meta["audio"]:
        raise ValueError("Performance recording must contain both video and audio")
    if meta["duration"] > 3600:
        raise ValueError("Source is limited to one hour per project")
    folder = Path(folder)
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", folder / "master.wav"])
    run(["ffmpeg", "-v", "error", "-y", "-i", path, "-frames:v", "1", "-vf", "scale=1024:-2", folder / "source.png"])
    return meta


def extract_frame(source, output, seconds, width=768):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{seconds:.8f}", "-i", source,
         "-frames:v", "1", "-vf", f"scale={width}:-2", output])
    return output


def audio_slice(path, start_frame, num_frames, fps):
    """PCM16 -> float AUDIO array, padded to exact requested sample count."""
    import numpy as np
    with wave.open(str(path), "rb") as stream:
        sr, channels = stream.getframerate(), stream.getnchannels()
        if stream.getsampwidth() != 2:
            raise ValueError("Expected prepared PCM16 master audio")
        start = round(start_frame * sr / fps)
        count = round(num_frames * sr / fps)
        stream.setpos(min(start, stream.getnframes()))
        data = np.frombuffer(stream.readframes(count), dtype="<i2").astype(np.float32) / 32768.0
        data = data.reshape(-1, channels).T
        if data.shape[1] < count:
            data = np.pad(data, ((0, 0), (0, count - data.shape[1])))
        return data, sr


def validate_clip(path, spec):
    meta = probe(path)
    video = meta["video"]
    if not video:
        raise ValueError("Renderer did not produce a video stream")
    # A missing tail must never be hidden by stretching the performance.
    required = (spec["trim_start"] + spec["edit_frames"]) / spec["fps"]
    video_duration = float(video.get("duration") or meta["duration"])
    if video_duration + .5 / spec["fps"] < required:
        raise ValueError(f"Rendered clip too short: {video_duration:.3f}s; need {required:.3f}s")
    return {"technical_pass": True, "duration": video_duration,
            "width": video["width"], "height": video["height"],
            "visual_review": "required", "lip_sync": "not measured"}


def assemble(store, project, width=1280, height=720):
    """Normalize visuals to exact frames and mux the untouched master timeline once."""
    from .core import render_key, shot_spec, digest
    if not project["shots"]:
        raise ValueError("Plan shots first")
    if width % 2 or height % 2 or not 128 <= width <= 4096 or not 128 <= height <= 4096:
        raise ValueError("Export dimensions must be even and between 128 and 4096")
    chosen = []
    for shot in project["shots"]:
        candidate = next((c for c in shot.get("candidates", []) if c["id"] == shot.get("selected")), None)
        if not candidate or candidate["key"] != render_key(project, shot) or not candidate.get("approved"):
            raise ValueError(f"{shot['id']}: approve a current render before export")
        chosen.append((shot, candidate))
    key = digest({"candidates": [c["id"] for _, c in chosen], "width": width, "height": height})
    relative = f"exports/{key}"
    folder = store.asset(project["id"], relative)
    folder.mkdir(parents=True, exist_ok=True)
    fps = project["fps"]
    for i, (shot, candidate) in enumerate(chosen):
        source = store.asset(project["id"], candidate["file"])
        spec = shot_spec(project, shot)
        validate_clip(source, spec)
        start, count = spec["trim_start"], spec["edit_frames"]
        vf = (f"fps={fps},trim=start_frame={start}:end_frame={start+count},setpts=PTS-STARTPTS,"
              f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p")
        run(["ffmpeg", "-v", "error", "-y", "-i", source, "-an", "-vf", vf,
             "-frames:v", count, "-c:v", "libx264", "-preset", "fast", "-crf", "18", folder / f"part_{i:05d}.mp4"])
    manifest = folder / "concat.txt"
    manifest.write_text("".join(f"file 'part_{i:05d}.mp4'\n" for i in range(len(chosen))))
    master = store.asset(project["id"], project["assets"]["source"]["audio"])
    output = folder / "scene.mp4"
    duration = project["total_frames"] / fps
    run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "1", "-i", manifest,
         "-i", master, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-af", "apad",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{duration:.9f}", "-movflags", "+faststart", output], timeout=1800)
    # Preserve the lossless master as a separate deliverable; MP4 uses AAC.
    shutil.copy2(master, folder / "master.wav")
    (folder / "edit.json").write_text(json.dumps({"fps": fps, "total_frames": project["total_frames"],
        "shots": [{"id": s["id"], "start": s["start"], "end": s["end"], "candidate": c["file"],
                   "source_trim_frames": shot_spec(project, s)["trim_start"]} for s, c in chosen]}, indent=2))
    result = probe(output)
    if abs(result["duration"] - duration) > 1.5 / fps:
        raise RuntimeError("Export duration check failed")
    return {"file": f"{relative}/scene.mp4", "master": f"{relative}/master.wav", "edit": f"{relative}/edit.json",
            "duration": duration, "width": width, "height": height}
