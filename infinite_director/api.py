from __future__ import annotations
import asyncio
import copy
import functools
import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path

from .core import CAMERAS, identifier, invalidate, plan, render_key, validate_project, validate_transcript
from .engine import validate_template
from .direction import ROLES, plan_direction, reference_catalog
from .runtime import runtime


def register_routes():
    from aiohttp import web
    from server import PromptServer
    routes = PromptServer.instance.routes

    def route(method, path):
        def decorator(fn):
            @functools.wraps(fn)
            async def guarded(request):
                try:
                    return await fn(request)
                except web.HTTPException:
                    raise
                except (ValueError, KeyError, StopIteration, TypeError) as exc:
                    return web.json_response({"error": str(exc)}, status=400)
                except FileNotFoundError:
                    return web.json_response({"error": "Project or asset not found"}, status=404)
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).exception("Infinite Director request failed")
                    return web.json_response({"error": str(exc)}, status=500)
            getattr(routes, method)("/infinite-director" + path)(guarded)
            return guarded
        return decorator

    async def body(request):
        if request.content_length and request.content_length > 8 * 1024 * 1024:
            raise ValueError("JSON request exceeds 8 MiB")
        value = await request.json()
        if not isinstance(value, dict):
            raise ValueError("Expected a JSON object")
        return value

    def edit(pid, fn, revision=None):
        store, engine = runtime()
        with engine.lock:
            engine.idle(pid)
            return store.update(pid, fn, revision)

    @route("get", "/health")
    async def health(request):
        return web.json_response({"version": "0.2.0", "ffmpeg": bool(shutil.which("ffmpeg")),
                                  "ffprobe": bool(shutil.which("ffprobe")), "cameras": CAMERAS})

    @route("get", "/projects")
    async def projects(request):
        return web.json_response(runtime()[0].list())

    @route("post", "/projects")
    async def create(request):
        data = await body(request)
        return web.json_response(runtime()[0].create(data.get("name", "Untitled scene"), data.get("fps", 24)))

    @route("get", "/projects/{pid}")
    async def get_project(request):
        store, engine = runtime()
        p = store.read(request.match_info["pid"])
        from .direction import design_key
        for design in p.get("designs", []):
            design["stale"] = design.get("key") != design_key(p, design)
        # Large templates stay server-side; the editor needs status and model names only.
        p["templates"] = {role: {"hash": t["hash"], "output_node": t["output_node"],
            "nodes": len(t["graph"])} for role, t in p["templates"].items()}
        from .core import shot_spec
        for shot in p["shots"]:
            shot["compiled"] = shot_spec(p, shot)
        p["busy"] = engine.busy(p["id"])
        return web.json_response(p)

    @route("patch", "/projects/{pid}")
    async def update_project(request):
        data = await body(request)
        def change(p):
            for key in ("name", "bible", "direction"):
                if key in data:
                    if not isinstance(data[key], str) or len(data[key]) > 16000:
                        raise ValueError("Invalid text field")
                    p[key] = data[key]
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/assets/{kind}")
    async def upload(request):
        from PIL import Image, ImageOps
        from .media import prepare_source
        pid, kind = request.match_info["pid"], request.match_info["kind"]
        store, engine = runtime()
        engine.idle(pid)
        initial = store.read(pid)
        if kind not in ("source", "character", "scene", "reference", "other"):
            raise ValueError("Invalid asset type")
        sid = request.query.get("shot_id")
        if kind == "reference" and sid not in {s["id"] for s in initial["shots"]}:
            raise ValueError("Select an existing shot")
        reader = await request.multipart()
        part = await reader.next()
        if part is None or part.name != "file":
            raise ValueError("Expected multipart file field")
        token = uuid.uuid4().hex[:16]
        relative = f"assets/{token}"
        folder = store.asset(pid, relative)
        folder.mkdir(parents=True)
        path = folder / "upload.bin"
        checksum, size = hashlib.sha256(), 0
        try:
            with path.open("wb") as handle:
                while chunk := await part.read_chunk(1024 * 1024):
                    size += len(chunk)
                    if size > (2 * 1024**3 if kind in ("source", "other") else 32 * 1024**2):
                        raise ValueError("Upload exceeds size limit")
                    checksum.update(chunk)
                    handle.write(chunk)
            if kind == "source":
                # Sniff actual streams; user filename is never used as a filesystem path.
                meta = await asyncio.to_thread(prepare_source, path, folder)
                source_name = "performance" + (Path(part.filename or "").suffix.lower() if Path(part.filename or "").suffix.lower() in (".mp4", ".mov", ".mkv", ".webm") else ".mp4")
                path.rename(folder / source_name)
                asset = {"file": f"{relative}/{source_name}", "audio": f"{relative}/master.wav",
                         "poster": f"{relative}/source.png", "hash": checksum.hexdigest(), "duration": meta["duration"]}
            elif kind == "other":
                from .media import probe, extract_frame
                role = request.query.get("role", "general")
                if role not in ROLES: raise ValueError("Unknown reference role")
                try:
                    with Image.open(path) as im:
                        if im.width * im.height > 40_000_000: raise ValueError("Image exceeds 40 megapixels")
                        ImageOps.exif_transpose(im).convert("RGB").save(folder / "image.png")
                    path.unlink()
                    asset = {"file": f"{relative}/image.png", "media_type": "image"}
                except (Image.UnidentifiedImageError, OSError):
                    meta = await asyncio.to_thread(probe, path)
                    if not meta["video"] or meta["duration"] > 3600: raise ValueError("Expected an image or a video shorter than one hour")
                    extension = Path(part.filename or "").suffix.lower()
                    if extension not in (".mp4", ".mov", ".mkv", ".webm"): extension = ".mp4"
                    path.rename(folder / ("reference" + extension))
                    await asyncio.to_thread(extract_frame, folder / ("reference" + extension), folder / "poster.jpg", 0)
                    asset = {"file": f"{relative}/reference{extension}", "poster": f"{relative}/poster.jpg", "media_type": "video", "duration": meta["duration"]}
                asset.update(id="ref_"+token[:8], label=Path(part.filename or "Reference").name[:120],
                             role=role, notes="", hash=checksum.hexdigest())
            else:
                with Image.open(path) as im:
                    if im.width * im.height > 40_000_000:
                        raise ValueError("Image exceeds 40 megapixels")
                    ImageOps.exif_transpose(im).convert("RGB").save(folder / "image.png")
                path.unlink()
                asset = {"file": f"{relative}/image.png", "hash": checksum.hexdigest()}
            def change(p):
                if kind == "other":
                    p["other_references"].append(asset)
                elif kind == "reference":
                    shot = next(s for s in p["shots"] if s["id"] == sid)
                    shot.update(reference_override=asset, reference=asset["file"])
                else:
                    p["assets"][kind] = asset
                if kind == "source":
                    p.update(total_frames=max(1, math.ceil(asset["duration"] * p["fps"])), shots=[], transcript=[], observations=[], designs=[])
                invalidate(p)
            result = edit(pid, change, initial["revision"])
            return web.json_response(result)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    @route("get", "/projects/{pid}/media")
    async def media(request):
        path = runtime()[0].asset(request.match_info["pid"], request.query.get("file", ""))
        if path.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm", ".wav", ".png", ".jpg", ".jpeg", ".webp"):
            raise ValueError("Not a media asset")
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={"X-Content-Type-Options": "nosniff"})

    @route("get", "/projects/{pid}/manifest")
    async def manifest(request):
        return web.json_response(runtime()[0].read(request.match_info["pid"]),
                                 headers={"Content-Disposition": 'attachment; filename="scene-manifest.json"'})

    @route("post", "/projects/{pid}/transcript")
    async def transcript(request):
        data = await body(request)
        def change(p):
            p["transcript"] = validate_transcript(data["segments"], p["assets"]["source"]["duration"])
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/plan")
    async def plan_scene(request):
        data = await body(request)
        def change(p):
            if "source" not in p["assets"]:
                raise ValueError("Upload a performance first")
            if p["shots"] and not data.get("replace"):
                raise ValueError("Planning replaces the edit. Set replace=true explicitly.")
            # Keep previous edits recoverable without making them active.
            if p["shots"]:
                p.setdefault("plan_history", []).append(copy.deepcopy(p["shots"]))
            plan_direction(p, data.get("target_seconds", 6))
            p.pop("export", None)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/intelligence")
    async def intelligence(request):
        from .intelligence import enrich, transcribe, observe, review_take, develop_scene
        pid, data = request.match_info["pid"], await body(request)
        store, engine = runtime()
        action = data.get("action")
        if action not in ("direct", "transcribe", "observe", "review", "develop"):
            raise ValueError("Unknown intelligence action")
        snapshot = store.read(pid)
        if "source" not in snapshot["assets"]:
            raise ValueError("Upload a performance first")
        if action == "direct" and not snapshot["shots"]:
            raise ValueError("Plan shots before directing")
        if action == "develop" and data.get("generate", True) and not snapshot["templates"].get("reference"):
            raise ValueError("Use bundled renderers or capture a Qwen renderer before generating preproduction assets")
        def work(cancel, jid):
            if action == "develop":
                result = develop_scene(store, snapshot, data.get("model", "qwen3.6:27b-q8_0"), cancel,
                                       lambda **kw: engine.progress(pid, jid, **kw))
                if result is None or cancel.is_set(): return
                def save(p):
                    for key in ("shots", "bible", "designs", "plan_notes", "planner", "plan_history", "agent_report", "reference_observations"):
                        if key in result: p[key] = result[key]
                    invalidate(p)
                store.update(pid, save)
                if data.get("generate", True):
                    info = engine.client.request("/object_info")
                    template = result["templates"]["reference"]
                    validate_template(template["graph"], "reference", template["output_node"], info)
                    engine.generate_designs(result, cancel, jid)
                    engine.generate_references(result, result["shots"], cancel, jid)
                engine.progress(pid, jid, phase="audit", message="Review the scene bible, design sheets, prompts and camera images before video generation")
                return
            if action == "direct":
                result = enrich(snapshot, data.get("model", "qwen3.6:27b-q8_0"))
                def change(p):
                    p.update(shots=result["shots"], planner=result["planner"])
                    invalidate(p)
            elif action == "transcribe":
                source = snapshot["assets"]["source"]
                result = transcribe(store.asset(pid, source["audio"]), source["duration"], data.get("model", ""))
                def change(p):
                    p["transcript"] = result
                    invalidate(p)
            elif action == "review":
                take_id, result = review_take(store, snapshot, data.get("shot_id", ""), data.get("model", "qwen3.6:27b-q8_0"))
                def change(p):
                    shot = next(s for s in p["shots"] if s["id"] == data["shot_id"])
                    next(c for c in shot["candidates"] if c["id"] == take_id)["visual_review"] = result
            else:
                result = observe(store, snapshot, data.get("model", "qwen3.6:27b-q8_0"))
                def change(p):
                    p["observations"] = result
            if not cancel.is_set():
                store.update(pid, change)
        return web.json_response({"job_id": engine.start(pid, action, work, expected_revision=snapshot["revision"])})

    @route("patch", "/projects/{pid}/shots/{sid}")
    async def update_shot(request):
        data = await body(request)
        def change(p):
            shot = next(s for s in p["shots"] if s["id"] == request.match_info["sid"])
            changed = {k for k in ("camera", "camera_description", "action", "state_in", "state_out", "notes") if k in data and data[k] != shot.get(k, "")}
            if "camera" in changed and data.get("camera_description", shot.get("camera_description")) == shot.get("camera_description"):
                data["camera_description"] = ""
            for prompt in ("image_prompt", "video_prompt"):
                relevant = changed - ({"notes", "state_out"} if prompt == "image_prompt" else set())
                if relevant and data.get(prompt, shot.get(prompt)) == shot.get(prompt):
                    data[prompt] = ""
            for key in ("camera", "purpose", "action", "state_in", "state_out", "notes", "seed", "image_prompt", "video_prompt", "camera_description", "reference_ids"):
                if key in data:
                    shot[key] = data[key]
            if data.get("clear_reference"):
                shot.pop("reference_override", None)
                shot.pop("reference", None)
            from .direction import bound_references
            bound_references(p, shot)
            validate_project(p)
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/boundary")
    async def boundary(request):
        data = await body(request)
        def change(p):
            i = next(i for i, s in enumerate(p["shots"]) if s["id"] == data["shot_id"])
            if i == len(p["shots"]) - 1:
                raise ValueError("Final boundary is fixed by source duration")
            p["shots"][i]["end"] = data["frame"]
            p["shots"][i+1]["start"] = data["frame"]
            validate_project(p)
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/shots/{sid}/select")
    async def select(request):
        data = await body(request)
        def change(p):
            shot = next(s for s in p["shots"] if s["id"] == request.match_info["sid"])
            candidate = next(c for c in shot["candidates"] if c["id"] == data["candidate_id"])
            if candidate["key"] != render_key(p, shot):
                raise ValueError("This take is stale. Restore its settings or render again.")
            candidate["approved"] = bool(data.get("approved", False))
            shot.update(selected=candidate["id"], status="approved" if candidate["approved"] else "review")
            p.pop("export", None)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("patch", "/projects/{pid}/references/{rid}")
    async def update_reference(request):
        data = await body(request)
        def change(p):
            ref = next(r for r in p["other_references"] if r["id"] == request.match_info["rid"])
            for key in ("label", "notes", "role"):
                if key in data:
                    if not isinstance(data[key], str) or len(data[key]) > 4000: raise ValueError("Invalid reference metadata")
                    if key == "role" and data[key] not in ROLES: raise ValueError("Invalid reference role")
                    ref[key] = data[key]
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("patch", "/projects/{pid}/designs/{did}")
    async def update_design(request):
        data = await body(request)
        def change(p):
            design = next(d for d in p["designs"] if d["id"] == request.match_info["did"])
            prompt = data.get("prompt", design["prompt"])
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 12000:
                raise ValueError("Invalid design prompt")
            design["prompt"] = prompt
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("delete", "/projects/{pid}/references/{rid}")
    async def delete_reference(request):
        data = await body(request)
        rid = request.match_info["rid"]
        def change(p):
            if rid not in {r["id"] for r in p["other_references"]}: raise ValueError("Unknown reference")
            p["other_references"] = [r for r in p["other_references"] if r["id"] != rid]
            if rid == "ref_legacy_scene": p["assets"].pop("scene", None)
            for item in p["shots"] + p["designs"]:
                item["reference_ids"] = [r for r in item.get("reference_ids", []) if r != rid]
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/templates/bundled")
    async def bundled_templates(request):
        data = await body(request)
        store, engine = runtime()
        info = await asyncio.to_thread(engine.client.request, "/object_info")
        root = Path(__file__).resolve().parent.parent / "workflows"
        templates = {}
        for role, filename in (("reference", "02-qwen-reference.api.json"), ("video", "03-ltx25-audio-video.api.json")):
            graph = json.loads((root / filename).read_text())
            templates[role] = validate_template(graph, role, info=info)
        def change(p):
            p["templates"].update(templates)
            invalidate(p)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/templates/{role}")
    async def template(request):
        data = await body(request)
        store, engine = runtime()
        info = await asyncio.to_thread(engine.client.request, "/object_info")
        value = validate_template(data["graph"], request.match_info["role"], data.get("output_node"), info)
        def change(p):
            p["templates"][value["role"]] = value
            invalidate(p)
        edit(request.match_info["pid"], change, data.get("revision"))
        return web.json_response({"hash": value["hash"], "output_node": value["output_node"]})

    @route("post", "/projects/{pid}/render")
    async def render(request):
        data = await body(request)
        jid = await asyncio.to_thread(runtime()[1].render, request.match_info["pid"], data.get("shot_ids"), data.get("retries", 1), bool(data.get("force", False)), data.get("stage", "video"))
        return web.json_response({"job_id": jid})

    @route("post", "/projects/{pid}/cancel")
    async def cancel(request):
        runtime()[1].cancel(request.match_info["pid"])
        return web.json_response({"ok": True})

    @route("post", "/projects/{pid}/export")
    async def export(request):
        from .media import assemble
        pid, data = request.match_info["pid"], await body(request)
        store, engine = runtime()
        def work(cancel, jid):
            result = assemble(store, store.read(pid), int(data.get("width", 1280)), int(data.get("height", 720)))
            if not cancel.is_set():
                store.update(pid, lambda p: p.update(export=result))
        return web.json_response({"job_id": engine.start(pid, "export", work)})

    @route("get", "/workflows/{name}")
    async def workflow(request):
        name = request.match_info["name"]
        if name not in ("01-director.json", "02-qwen-reference.json", "03-ltx25-audio-video.json"):
            raise ValueError("Unknown bundled workflow")
        return web.FileResponse(Path(__file__).resolve().parent.parent / "workflows" / name)
