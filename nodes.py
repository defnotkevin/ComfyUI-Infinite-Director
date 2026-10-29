from __future__ import annotations
import json
import math
from .infinite_director.core import identifier, plan, shot_spec, validate_project
from .infinite_director.runtime import runtime
from .infinite_director.direction import bound_references, current_designs


class IDShotInputs:
    """Bridge any image/video workflow to the scene scheduler."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": ""}),
                             "shot_id": ("STRING", {"default": "shot_0001"}),
                             "job_id": ("STRING", {"default": "", "tooltip": "Filled by the render scheduler. Leave blank for manual preview."})}}
    RETURN_TYPES = ("STRING", "STRING", "IMAGE", "IMAGE", "IMAGE", "AUDIO", "FLOAT", "INT", "FLOAT", "INT", "STRING")
    RETURN_NAMES = ("video_prompt", "reference_prompt", "shot_image", "character", "other_references", "audio", "fps", "num_frames", "duration", "seed", "filename_prefix")
    FUNCTION = "load"
    CATEGORY = "Infinite Director"
    DESCRIPTION = "Immutable shot inputs for Qwen reference generation and LTX audio-to-video. Audio includes trim handles and legal-frame padding."

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        # Manual previews reflect edits; context jobs are immutable, but always loading avoids stale files.
        return float("nan")

    def load(self, project_id, shot_id, job_id=""):
        import numpy as np
        import torch
        from PIL import Image, ImageOps
        from .infinite_director.media import audio_slice
        store, _ = runtime()
        identifier(project_id)
        identifier(shot_id)
        if job_id:
            identifier(job_id)
            context = json.loads(store.asset(project_id, f"contexts/{job_id}.json").read_text())
            if context["project_id"] != project_id or context["shot_id"] != shot_id:
                raise ValueError("Render context does not match shot")
        else:
            project = store.read(project_id)
            shot = next((s for s in project["shots"] if s["id"] == shot_id), None)
            if not shot:
                raise ValueError("Shot not found. Open Infinite Director and plan a scene first.")
            context = {"spec": shot_spec(project, shot), "assets": project["assets"],
                       "reference": shot.get("reference_override", {}).get("file") or shot.get("reference"),
                       "references": bound_references(project, shot),
                       "designs": current_designs(project)}
        assets, spec = context["assets"], context["spec"]
        if "source" not in assets:
            raise ValueError("Upload a performance first")
        def image(relative):
            with Image.open(store.asset(project_id, relative)) as im:
                array = np.asarray(ImageOps.exif_transpose(im).convert("RGB"), dtype=np.float32).copy() / 255.0
            return torch.from_numpy(array)[None, ...]
        from .infinite_director.references import make_board
        designs = context.get("designs", [])
        character_file = next((d["file"] for d in designs if d["kind"] == "character"), None) or assets.get("character", {}).get("file") or assets["source"]["poster"]
        scene_file = assets.get("scene", {}).get("file") or assets["source"]["poster"]
        character, scene = image(character_file), image(scene_file)
        board = make_board(store, project_id, context.get("references", []), designs)
        if board is not None:
            scene = torch.from_numpy(np.asarray(board, dtype=np.float32).copy() / 255.0)[None, ...]
        shot_image = image(context["reference"]) if context.get("reference") else character
        waveform, sr = audio_slice(store.asset(project_id, assets["source"]["audio"]), spec["render_start"], spec["num_frames"], spec["fps"])
        audio = {"waveform": torch.from_numpy(waveform)[None, ...], "sample_rate": sr}
        return (spec["prompt"], spec["reference_prompt"], shot_image, character, scene, audio, float(spec["fps"]),
                spec["num_frames"], spec["duration"], spec["seed"], f"infinite_director_renders/{project_id}/{shot_id}/{job_id or 'manual'}")


class IDScenePlan:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": ""})}}
    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("scene_json", "shot_count")
    FUNCTION = "read"
    CATEGORY = "Infinite Director"
    OUTPUT_NODE = True
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")
    def read(self, project_id):
        store, _ = runtime()
        project = validate_project(store.read(project_id))
        text = json.dumps({"id": project_id, "fps": project["fps"], "shots": [dict(s, compiled=shot_spec(project, s)) for s in project["shots"]]}, indent=2)
        return {"ui": {"text": [text]}, "result": (text, len(project["shots"]))}


class IDFrameCount:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"duration": ("FLOAT", {"default": 6., "min": .1, "max": 120}),
                             "fps": ("FLOAT", {"default": 24., "min": 1, "max": 60})}}
    RETURN_TYPES = ("INT", "FLOAT")
    RETURN_NAMES = ("num_frames", "actual_duration")
    FUNCTION = "count"
    CATEGORY = "Infinite Director"
    def count(self, duration, fps):
        if not math.isfinite(duration) or not math.isfinite(fps) or duration <= 0 or fps <= 0:
            raise ValueError("Duration and frame rate must be positive and finite")
        count = 1 + 8 * math.ceil((math.ceil(duration * fps) - 1) / 8)
        return count, count / fps


class IDExportScene:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": ""}),
                             "width": ("INT", {"default": 1280, "min": 128, "max": 4096, "step": 2}),
                             "height": ("INT", {"default": 720, "min": 128, "max": 4096, "step": 2})}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("export_path",)
    FUNCTION = "export"
    CATEGORY = "Infinite Director"
    OUTPUT_NODE = True
    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")
    def export(self, project_id, width, height):
        from .infinite_director.media import assemble
        store, engine = runtime()
        with engine.lock:
            engine.idle(project_id)
            project = store.read(project_id)
            result = assemble(store, project, width, height)
            store.update(project_id, lambda p: p.update(export=result))
        path = str(store.asset(project_id, result["file"]))
        return {"ui": {"text": [path]}, "result": (path,)}


class IDGPUStage:
    """Internal queue barrier. Serializes memory cleanup and reasoning with GPU prompts."""
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"project_id": ("STRING", {"default": ""}),
                             "context_id": ("STRING", {"default": ""})}}
    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "Infinite Director/internal"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def execute(self, project_id, context_id):
        from .infinite_director.gpu import execute_control
        identifier(project_id); identifier(context_id)
        store, _ = runtime()
        execute_control(store, project_id, context_id)
        return {"ui": {"text": ["GPU stage completed"]}}


NODE_CLASS_MAPPINGS = {c.__name__: c for c in (IDShotInputs, IDScenePlan, IDFrameCount, IDExportScene, IDGPUStage)}
NODE_DISPLAY_NAME_MAPPINGS = {"IDShotInputs": "Infinite Director · Shot Inputs", "IDScenePlan": "Infinite Director · Scene Plan",
                            "IDGPUStage": "Infinite Director · GPU Stage Handoff", "IDFrameCount": "Infinite Director · LTX Frame Count", "IDExportScene": "Infinite Director · Export Scene"}
