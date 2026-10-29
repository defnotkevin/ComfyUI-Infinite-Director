"""Frame-exact scene planning. Pure Python; no GPU or ComfyUI imports."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import threading
import uuid
from pathlib import Path
from datetime import datetime, timezone

SCHEMA = 1
CAMERAS = {
    "overhead": "Directly overhead view looking vertically down at the character",
    "right_profile": "Eye-level right profile of the character",
    "crane": "The camera cranes upward and moves toward the character",
    "custom": "Use the explicitly described camera setup",
    "front": "Eye-level medium shot facing the character, locked camera",
    "three_quarter": "Eye-level close three-quarter view of the character, restrained slow push-in",
    "profile": "Eye-level medium close-up from the character's left side, locked camera",
    "wide": "Wide establishing view of the character and the established room, locked camera",
    "detail": "Close insert of the established prop and the character's hands, face outside frame",
    "cup_pov": "Extreme close-up from inside the established coffee cup looking upward past its rim toward the character; rim occludes the edges",
}
SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def identifier(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError("Invalid project, shot, or job identifier")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()[:24]


def now():
    return datetime.now(timezone.utc).isoformat()


def integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def validate_project(project):
    identifier(project["id"])
    fps = integer(project["fps"], "fps", 8, 60)
    total = integer(project["total_frames"], "total_frames", 1, 60 * 60 * fps)
    cursor, seen = 0, set()
    shots = project.get("shots", [])
    for shot in shots:
        sid = identifier(shot["id"])
        if sid in seen:
            raise ValueError("Duplicate shot ID")
        seen.add(sid)
        if integer(shot["start"], "start", 0, total) != cursor:
            raise ValueError("Shot intervals must cover the timeline without gaps or overlaps")
        cursor = integer(shot["end"], "end", shot["start"] + 1, total)
        if shot["camera"] not in CAMERAS:
            raise ValueError("Unknown camera")
        integer(shot.get("seed", 0), "seed", 0, 2**63 - 1)
        for key in ("purpose", "action", "state_in", "state_out", "notes", "image_prompt", "video_prompt", "camera_description", "direction_text"):
            if not isinstance(shot.get(key, ""), str) or len(shot.get(key, "")) > 12000:
                raise ValueError(f"Invalid shot {key}")
    if shots and cursor != total:
        raise ValueError("Shots do not cover the entire performance")
    return project


def validate_transcript(segments, duration):
    if not isinstance(segments, list) or len(segments) > 20000:
        raise ValueError("Transcript must be a list of timestamped segments")
    result, previous = [], 0.0
    for s in segments:
        a, b = float(s["start"]), float(s["end"])
        if not (math.isfinite(a) and math.isfinite(b) and 0 <= a < b <= duration + .1 and a >= previous):
            raise ValueError("Transcript timestamps must be ordered, finite, and within the source")
        text = str(s["text"]).strip()
        if len(text) > 12000:
            raise ValueError("Transcript segment is too long")
        result.append({"start": a, "end": b, "text": text})
        previous = a
    return result


def plan(project, target_seconds=6):
    """Choose boundaries near utterance ends; always cover exact output frame count."""
    target_seconds = float(target_seconds)
    if not math.isfinite(target_seconds) or not 2 <= target_seconds <= 12:
        raise ValueError("Target shot duration must be 2–12 seconds")
    fps, total = project["fps"], project["total_frames"]
    target = round(target_seconds * fps)
    candidates = [round(s["end"] * fps) for s in project.get("transcript", [])]
    boundaries = [0]
    while total - boundaries[-1] > target * 1.4:
        start = boundaries[-1]
        options = [n for n in candidates if start + target * .65 <= n <= min(start + target * 1.35, total - fps)]
        end = min(options, key=lambda n: abs(n - start - target)) if options else min(total, start + target)
        boundaries.append(end)
    boundaries.append(total)
    cameras = ["front", "three_quarter", "wide", "profile", "three_quarter"]
    shots = []
    for i, (start, end) in enumerate(zip(boundaries, boundaries[1:])):
        shots.append({"id": f"shot_{i+1:04d}", "start": start, "end": end,
                      "camera": cameras[i % len(cameras)], "purpose": "Introduce the speaker" if i == 0 else "Develop the spoken beat",
                      "action": "The character delivers the supplied speech naturally. Keep gestures restrained.",
                      "state_in": "Maintain established clothing, seating, props, and eyeline.",
                      "state_out": "Preserve the established scene state.", "notes": "", "seed": 1000 + i,
                      "status": "planned", "candidates": [], "selected": None})
    project["shots"] = shots
    project["planner"] = "deterministic"
    return validate_project(project)


def dialogue(project, shot):
    return " ".join(s["text"] for s in project.get("transcript", [])
                    if s["end"] > shot["start"] / project["fps"] and s["start"] < shot["end"] / project["fps"])


def shot_spec(project, shot):
    fps = project["fps"]
    handles = round(project.get("handles_seconds", .25) * fps)
    render_start = max(0, shot["start"] - handles)
    desired = min(project["total_frames"], shot["end"] + handles) - render_start
    frames = 1 + 8 * math.ceil((desired - 1) / 8)
    bible = project.get("bible", "")
    camera = shot.get("camera_description") or CAMERAS[shot["camera"]]
    visual = f"{camera}. {bible} {shot['state_in']} {shot['action']} {shot.get('direction_text', '')}"
    reference_prompt = f"Create one cinematic still, not a collage. Preserve the supplied character's identity and wardrobe. {visual}"
    video_prompt = (f"{visual} By the end of the shot: {shot['state_out']} "
                    "The original recorded speech continues naturally with synchronized mouth movement when the face is visible. "
                    "One continuous camera setup; no internal cuts. " + shot.get("notes", ""))
    reference_prompt = shot.get("image_prompt") or reference_prompt
    video_prompt = shot.get("video_prompt") or video_prompt
    # The canonical continuity record remains effective after manual bible edits.
    reference_prompt += f"\nContinuity constraints: {bible}"
    video_prompt += f"\nContinuity constraints: {bible}"
    return {"shot_id": shot["id"], "prompt": video_prompt, "reference_prompt": reference_prompt,
            "dialogue": dialogue(project, shot), "render_start": render_start, "num_frames": frames,
            "trim_start": shot["start"] - render_start, "edit_frames": shot["end"] - shot["start"],
            "duration": frames / fps, "fps": fps, "seed": shot["seed"]}


def reference_key(project, shot):
    from .direction import bound_references, current_designs
    return digest({"prompt": shot_spec(project, shot)["reference_prompt"],
                   "character": project.get("assets", {}).get("character"),
                   "source": project.get("assets", {}).get("source"),
                   "scene": project.get("assets", {}).get("scene"),
                   "references": bound_references(project, shot),
                   "designs": [{"id":d["id"],"key":d["key"]} for d in current_designs(project)],
                   "canvas": project.get("canvas_reference_signature"), "template": project.get("templates", {}).get("reference"), "seed": shot["seed"]})


def render_key(project, shot):
    return digest({"spec": shot_spec(project, shot), "reference": reference_key(project, shot),
                   "override": shot.get("reference_override"), "source": project.get("assets", {}).get("source"),
                   "canvas": project.get("canvas_video_signature"), "template": project.get("templates", {}).get("video")})


def invalidate(project):
    """Only selected outputs with matching dependencies remain eligible for assembly."""
    for shot in project["shots"]:
        key = render_key(project, shot)
        if not shot.get("reference_override") and shot.get("reference") != f"references/{reference_key(project, shot)}.png":
            shot.pop("reference", None)
        candidates = [c for c in shot.get("candidates", []) if c["key"] == key]
        selected = next((c for c in candidates if c["id"] == shot.get("selected")), None)
        if not selected:
            shot["selected"] = None
            shot["status"] = "planned"
        else:
            shot["status"] = "approved" if selected.get("approved") else "review"
    project.pop("export", None)
    return project


class Store:
    """Atomic project writes with revision checks and process-local serialization."""
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()

    def folder(self, pid):
        return self.root / identifier(pid)

    def asset(self, pid, relative):
        root = self.folder(pid).resolve()
        path = (root / relative).resolve()
        if not path.is_relative_to(root) or path == root:
            raise ValueError("Asset must be inside its project directory")
        return path

    def create(self, name, fps=24):
        integer(fps, "fps", 8, 60)
        pid = uuid.uuid4().hex[:12]
        p = {"schema": SCHEMA, "id": pid, "name": str(name)[:160] or "Untitled scene", "revision": 0,
             "created": now(), "updated": now(), "fps": fps, "total_frames": 1, "bible": "",
             "direction": "A cinematic scene with restrained, motivated cuts.", "handles_seconds": .25,
             "assets": {}, "templates": {}, "transcript": [], "shots": [], "jobs": []}
        self.folder(pid).mkdir()
        self.write(p)
        return p

    def read(self, pid):
        with self.lock:
            from .direction import migrate
            return migrate(json.loads((self.folder(pid) / "project.json").read_text()))

    def write(self, project):
        validate_project(project)
        path = self.folder(project["id"]) / "project.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(project, indent=2, allow_nan=False))
        temp.replace(path)

    def update(self, pid, callback, revision=None):
        with self.lock:
            project = self.read(pid)
            if revision is not None and revision != project["revision"]:
                raise ValueError("This project changed in another window. Refresh before editing.")
            callback(project)
            project["revision"] += 1
            project["updated"] = now()
            self.write(project)
            return project

    def list(self):
        with self.lock:
            rows = []
            for path in self.root.glob("*/project.json"):
                try:
                    p = json.loads(path.read_text())
                    rows.append({k: p[k] for k in ("id", "name", "updated", "revision")})
                except (ValueError, KeyError, OSError):
                    continue
            return sorted(rows, key=lambda p: p["updated"], reverse=True)
