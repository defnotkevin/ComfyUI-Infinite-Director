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
        return web.json_response({"version": "0.1.0", "ffmpeg": bool(shutil.which("ffmpeg")),
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
        # Large templates stay server-side; the editor needs status and model names only.
        p["templates"] = {role: {"hash": t["hash"], "output_node": t["output_node"],
            "nodes": len(t["graph"])} for role, t in p["templates"].items()}
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
        if kind not in ("source", "character", "scene", "reference"):
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
                    if size > (2 * 1024**3 if kind == "source" else 32 * 1024**2):
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
            else:
                with Image.open(path) as im:
                    if im.width * im.height > 40_000_000:
                        raise ValueError("Image exceeds 40 megapixels")
                    ImageOps.exif_transpose(im).convert("RGB").save(folder / "image.png")
                path.unlink()
                asset = {"file": f"{relative}/image.png", "hash": checksum.hexdigest()}
            def change(p):
                if kind == "reference":
                    shot = next(s for s in p["shots"] if s["id"] == sid)
                    shot.update(reference_override=asset, reference=asset["file"])
                else:
                    p["assets"][kind] = asset
                if kind == "source":
                    p.update(total_frames=max(1, math.ceil(asset["duration"] * p["fps"])), shots=[], transcript=[], observations=[])
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
            plan(p, data.get("target_seconds", 6))
            p.pop("export", None)
        return web.json_response(edit(request.match_info["pid"], change, data.get("revision")))

    @route("post", "/projects/{pid}/intelligence")
    async def intelligence(request):
        from .intelligence import enrich, transcribe, observe, review_take
        pid, data = request.match_info["pid"], await body(request)
        store, engine = runtime()
        action = data.get("action")
        if action not in ("direct", "transcribe", "observe", "review"):
            raise ValueError("Unknown intelligence action")
        snapshot = store.read(pid)
        if "source" not in snapshot["assets"]:
            raise ValueError("Upload a performance first")
        if action == "direct" and not snapshot["shots"]:
            raise ValueError("Plan shots before directing")
        def work(cancel, jid):
            if action == "direct":
                result = enrich(snapshot, data.get("model", ""))
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
                take_id, result = review_take(store, snapshot, data.get("shot_id", ""), data.get("model", ""))
                def change(p):
                    shot = next(s for s in p["shots"] if s["id"] == data["shot_id"])
                    next(c for c in shot["candidates"] if c["id"] == take_id)["visual_review"] = result
            else:
                result = observe(store, snapshot, data.get("model", ""))
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
            for key in ("camera", "purpose", "action", "state_in", "state_out", "notes", "seed"):
                if key in data:
                    shot[key] = data[key]
            if data.get("clear_reference"):
                shot.pop("reference_override", None)
                shot.pop("reference", None)
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
        jid = await asyncio.to_thread(runtime()[1].render, request.match_info["pid"], data.get("shot_ids"), data.get("retries", 1), bool(data.get("force", False)))
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
