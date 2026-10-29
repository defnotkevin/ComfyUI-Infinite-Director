"""Resumable orchestration of ordinary ComfyUI API graphs."""
from __future__ import annotations
import copy
import json
import shutil
import threading
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path

from .core import digest, identifier, invalidate, now, reference_key, render_key, shot_spec
from .media import validate_clip
from .direction import bound_references, current_designs, design_key
from .intelligence import local_url


class Cancelled(RuntimeError):
    pass


def validate_template(graph, role, output_node=None, info=None):
    if role not in ("reference", "video") or not isinstance(graph, dict) or not graph or "nodes" in graph:
        raise ValueError("Use an API-format graph, or capture the current ComfyUI canvas")
    if len(graph) > 3000:
        raise ValueError("Template is too large")
    bridges = []
    for nid, node in graph.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict) or not isinstance(node.get("class_type"), str):
            raise ValueError(f"Invalid API node {nid}")
        cls = node["class_type"]
        if cls == "IDShotInputs":
            bridges.append(str(nid))
        if info is not None:
            if cls not in info:
                raise ValueError(f"Missing ComfyUI node: {cls}")
            metadata = info[cls]
            if metadata.get("api_node") or metadata.get("is_api_node") or "partner/" in metadata.get("category", ""):
                raise ValueError(f"Open-weights mode rejects partner API node: {cls}")
    if len(bridges) != 1:
        raise ValueError("Template must contain exactly one Infinite Director · Shot Inputs node")
    if output_node is None:
        allowed = ("SaveImage",) if role == "reference" else ("SaveVideo", "VHS_VideoCombine")
        candidates = [str(n) for n, v in graph.items() if v["class_type"] in allowed]
        if len(candidates) != 1:
            raise ValueError(f"Template needs exactly one {'SaveImage' if role == 'reference' else 'SaveVideo'} output, or an explicit output_node")
        output_node = candidates[0]
    if str(output_node) not in graph:
        raise ValueError("Output node does not exist")
    # Reject disconnected bridges: the selected output must depend on shot inputs.
    def depends(nid, seen=None):
        seen = set() if seen is None else seen
        if nid in seen:
            return False
        if nid == bridges[0]:
            return True
        seen.add(nid)
        values = graph[nid]["inputs"].values()
        return any(depends(str(v[0]), seen) for v in values
                   if isinstance(v, list) and len(v) == 2 and str(v[0]) in graph and isinstance(v[1], int))
    if not depends(str(output_node)):
        raise ValueError("Selected output is not connected to Shot Inputs")
    return {"graph": graph, "role": role, "output_node": str(output_node), "bridge": bridges[0], "hash": digest(graph)}


def bind_template(template, pid, sid, job_id):
    graph = copy.deepcopy(template["graph"])
    bridge = graph[template["bridge"]]["inputs"]
    bridge.update(project_id=pid, shot_id=sid, job_id=job_id)
    return graph


class ComfyClient:
    def __init__(self, base, output_root, temp_root):
        self.base = local_url(base)
        self.roots = {"output": Path(output_root).resolve(), "temp": Path(temp_root).resolve()}

    def request(self, path, data=None):
        request = urllib.request.Request(self.base + path, data=None if data is None else json.dumps(data).encode(),
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"ComfyUI rejected request: {exc.read().decode(errors='replace')[-3000:]}") from exc

    def execute(self, graph, output_node, role, cancel, on_queued=lambda _: None, timeout=3600):
        reply = self.request("/prompt", {"prompt": graph, "client_id": "infinite-director"})
        if reply.get("error") or reply.get("node_errors") or not reply.get("prompt_id"):
            raise RuntimeError(json.dumps(reply))
        prompt_id = reply["prompt_id"]
        on_queued(prompt_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel.is_set():
                # Remove only our pending prompt. Never interrupt another user's GPU job.
                self.request("/queue", {"delete": [prompt_id]})
                raise Cancelled("Cancelled. An already-running ComfyUI prompt may finish in the background.")
            history = self.request("/history/" + prompt_id).get(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(json.dumps(status.get("messages", []))[-3000:])
                outputs = history.get("outputs", {}).get(str(output_node), {})
                files = []
                for value in outputs.values():
                    if isinstance(value, list):
                        files.extend(v for v in value if isinstance(v, dict) and "filename" in v)
                extensions = (".png", ".jpg", ".jpeg", ".webp") if role == "reference" else (".mp4", ".webm", ".mov", ".mkv")
                files = [f for f in files if str(f["filename"]).lower().endswith(extensions)]
                # SaveVideo may expose the same artifact under more than one key.
                files = list({(f.get("type", "output"), f.get("subfolder", ""), f["filename"]): f for f in files}.values())
                if len(files) != 1:
                    raise RuntimeError(f"Expected one {role} artifact from output {output_node}; found {len(files)}")
                f = files[0]
                root = self.roots.get(f.get("type", "output"))
                if root is None:
                    raise ValueError("Renderer artifact must be in ComfyUI output or temp")
                path = (root / f.get("subfolder", "") / f["filename"]).resolve()
                if not path.is_relative_to(root) or not path.is_file():
                    raise ValueError("Invalid renderer artifact path")
                return path
            cancel.wait(1)
        self.request("/queue", {"delete": [prompt_id]})
        raise TimeoutError("ComfyUI render exceeded one hour; running GPU prompt was not globally interrupted")

    def control(self, store, pid, payload, cancel, on_queued=lambda _: None, timeout=1800):
        token = uuid.uuid4().hex[:16]
        context = store.asset(pid, f"contexts/{token}.gpu.json")
        context.parent.mkdir(exist_ok=True)
        context.write_text(json.dumps(payload))
        if cancel.is_set(): raise Cancelled("Cancelled before GPU handoff")
        graph = {"1": {"class_type": "IDGPUStage", "inputs": {"project_id": pid, "context_id": token}}}
        reply = self.request("/prompt", {"prompt": graph, "client_id": "infinite-director"})
        if reply.get("error") or reply.get("node_errors") or not reply.get("prompt_id"):
            raise RuntimeError(f"GPU handoff rejected; restart ComfyUI to register IDGPUStage: {reply}")
        prompt_id = reply["prompt_id"]; on_queued(prompt_id)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cancel.is_set():
                self.request("/queue", {"delete": [prompt_id]})
                raise Cancelled("Cancelled. Running GPU cleanup/reasoning finishes safely on the ComfyUI worker.")
            history = self.request("/history/" + prompt_id).get(prompt_id)
            if history:
                if history.get("status", {}).get("status_str") == "error":
                    raise RuntimeError(str(history.get("status", {}).get("messages", []))[-3000:])
                return json.loads(store.asset(pid, f"contexts/{token}.result.json").read_text())
            cancel.wait(.25)
        self.request("/queue", {"delete": [prompt_id]})
        raise TimeoutError("GPU handoff timed out; any running prompt is left to finish safely")


class Engine:
    def __init__(self, store, client):
        self.store, self.client = store, client
        self.lock = threading.RLock()
        self.active = {}
        self.gpu_lock = threading.Lock()
        self.stage = None
        # Jobs cannot resume automatically after restart: prompt completion is ambiguous.
        for summary in store.list():
            def recover(p):
                for job in p.get("jobs", []):
                    if job["status"] in ("queued", "running"):
                        job.update(status="interrupted", error="ComfyUI restarted. Completed assets are cached; resume explicitly.")
            if any(j["status"] in ("queued", "running") for j in store.read(summary["id"]).get("jobs", [])):
                store.update(summary["id"], recover)

    def busy(self, pid):
        with self.lock:
            return pid in self.active

    def idle(self, pid):
        if self.busy(pid):
            raise ValueError("Project has an active operation. Cancel or wait before editing.")

    def start(self, pid, kind, task, expected_revision=None):
        with self.lock:
            self.idle(pid)
            if expected_revision is not None and self.store.read(pid)["revision"] != expected_revision:
                raise ValueError("Project changed while preparing operation. Refresh and retry.")
            cancel = threading.Event()
            jid = uuid.uuid4().hex[:16]
            self.active[pid] = cancel
            try:
                self.store.update(pid, lambda p: p["jobs"].append({"id": jid, "kind": kind, "status": "queued", "created": now()}))
            except Exception:
                self.active.pop(pid, None)
                raise
            def worker():
                try:
                    while not self.gpu_lock.acquire(timeout=.25):
                        if cancel.is_set(): raise Cancelled("Cancelled while waiting for another director project")
                    try:
                        if cancel.is_set(): raise Cancelled("Cancelled before starting")
                        self.stage = None
                        self.progress(pid, jid, status="running")
                        from .intelligence import reasoning_backend
                        with reasoning_backend(lambda model, system, prompt, images=None:
                                self.reason(pid, jid, cancel, model, system, prompt, images)):
                            try:
                                task(cancel, jid)
                            finally:
                                if self.stage is not None:
                                    # Queue cleanup even after cancellation; never interrupt a running prompt.
                                    self.client.control(self.store, pid, {"action": "release"}, threading.Event())
                                    self.stage = None
                        self.progress(pid, jid, status="cancelled" if cancel.is_set() else "complete")
                    finally:
                        self.gpu_lock.release()
                except Cancelled as exc:
                    self.progress(pid, jid, status="cancelled", error=str(exc))
                except Exception as exc:
                    self.progress(pid, jid, status="failed", error=str(exc))
                finally:
                    with self.lock:
                        self.active.pop(pid, None)
            threading.Thread(target=worker, name=f"infinite-director-{jid}", daemon=True).start()
            return jid

    def progress(self, pid, jid, **values):
        def change(p):
            job = next(j for j in p["jobs"] if j["id"] == jid)
            job.update(values, updated=now())
        self.store.update(pid, change)

    def cancel(self, pid):
        with self.lock:
            if pid in self.active:
                self.active[pid].set()

    def reason(self, pid, jid, cancel, model, system, prompt, images=None):
        self.progress(pid, jid, phase="reasoning · GPU handoff")
        relative = [str(path.resolve().relative_to(self.store.folder(pid).resolve())) for path in (images or [])]
        self.stage = "reason"
        return self.client.control(self.store, pid,
            {"action":"reason", "model":model, "system":system, "prompt":prompt, "images":relative}, cancel,
            lambda prompt_id: self.progress(pid, jid, prompt_id=prompt_id))

    def enter_stage(self, pid, jid, role, cancel):
        if self.stage == role:
            return
        self.progress(pid, jid, phase=f"GPU cleanup → {role}")
        self.client.control(self.store, pid, {"action":"release"}, cancel,
            lambda prompt_id: self.progress(pid, jid, prompt_id=prompt_id))
        self.stage = role

    def render(self, pid, shot_ids=None, retries=1, force=False, stage="video"):
        if stage not in ("video", "references"):
            raise ValueError("Invalid render stage")
        if not isinstance(retries, int) or not 0 <= retries <= 3:
            raise ValueError("Retries must be 0–3")
        project = self.store.read(pid)
        if not project["shots"] or "source" not in project["assets"]:
            raise ValueError("Upload a performance and plan shots first")
        if shot_ids is not None and (not isinstance(shot_ids, list) or not all(isinstance(s, str) for s in shot_ids)):
            raise ValueError("shot_ids must be an array")
        selected = [s for s in project["shots"] if shot_ids is None or s["id"] in shot_ids]
        if not selected or (shot_ids is not None and set(shot_ids) != {s["id"] for s in selected}):
            raise ValueError("Unknown or empty shot selection")
        if stage == "video" and not project["templates"].get("video"):
            raise ValueError("Capture the LTX canvas as the video renderer first")
        info = self.client.request("/object_info")
        for template in project["templates"].values():
            validate_template(template["graph"], template["role"], template["output_node"], info)
        if not project["templates"].get("reference") and (project.get("designs") or any(not s.get("reference_override") for s in selected)):
            raise ValueError("Capture a reference renderer or upload an individual shot reference for every selected shot")
        def work(cancel, jid):
            # Freeze project data for all queued jobs. Editing is blocked while active.
            snapshot = self.store.read(pid)
            todo = [s for s in snapshot["shots"] if s["id"] in {x["id"] for x in selected}]
            self.generate_designs(snapshot, cancel, jid, retries)
            self.store.update(pid, invalidate)
            todo = [s for s in todo if stage == "references" or force or not any(c["key"] == render_key(snapshot, s) for c in s.get("candidates", []))]
            refs = self.generate_references(snapshot, todo, cancel, jid, retries)
            if stage == "references":
                self.progress(pid, jid, phase="audit", message="Sheets and camera references are ready to inspect")
                return
            for shot in todo:
                if cancel.is_set():
                    raise Cancelled("Cancelled between shots")
                self.progress(pid, jid, phase="video", shot=shot["id"])
                path, provenance = self.execute_shot(snapshot, shot, "video", refs[shot["id"]], jid, cancel, retries,
                                                     seed_offset=len(shot.get("candidates", [])) * 10000)
                spec = shot_spec(snapshot, shot)
                checks = validate_clip(path, spec)
                cid = uuid.uuid4().hex[:16]
                relative = f"takes/{shot['id']}/{cid}{path.suffix.lower()}"
                target = self.store.asset(pid, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                candidate = {"id": cid, "file": relative, "key": render_key(snapshot, shot), "approved": False,
                             "created": now(), "checks": checks, "reference": refs[shot["id"]], "provenance": provenance}
                def save(p):
                    live = next(s for s in p["shots"] if s["id"] == shot["id"])
                    live["candidates"].append(candidate)
                    live.update(selected=cid, status="review")
                    p.pop("export", None)
                self.store.update(pid, save)
            self.progress(pid, jid, phase="review", message="Rendered takes need visual approval before export")
        return self.start(pid, "render", work, expected_revision=project["revision"])

    def generate_designs(self, snapshot, cancel, jid, retries=1):
        pid = snapshot["id"]
        for design in snapshot.get("designs", []):
            if cancel.is_set(): raise Cancelled("Cancelled between sheets")
            key = design_key(snapshot, design)
            relative = f"designs/{key}.png"
            target = self.store.asset(pid, relative)
            if not target.exists():
                self.progress(pid, jid, phase="Qwen design sheet", sheet=design["label"])
                shot = dict(snapshot["shots"][0], id=design["id"], seed=design["seed"])
                path, provenance = self.execute_shot(snapshot, shot, "reference", None, jid, cancel, retries, design=design)
                from PIL import Image
                target.parent.mkdir(exist_ok=True)
                with Image.open(path) as image: image.convert("RGB").save(target)
                design["provenance"] = provenance
            design.update(file=relative, key=key)
            self.store.update(pid, lambda p, value=copy.deepcopy(design): next(d for d in p["designs"] if d["id"] == value["id"]).update(value))

    def generate_references(self, snapshot, shots, cancel, jid, retries=1):
        pid, refs = snapshot["id"], {}
        for shot in shots:
            if cancel.is_set(): raise Cancelled("Cancelled between references")
            if shot.get("reference_override"):
                refs[shot["id"]] = shot["reference_override"]["file"]
                continue
            relative = f"references/{reference_key(snapshot, shot)}.png"
            target = self.store.asset(pid, relative)
            if not target.exists():
                self.progress(pid, jid, phase="Qwen camera reference", shot=shot["id"])
                path, _ = self.execute_shot(snapshot, shot, "reference", None, jid, cancel, retries)
                from PIL import Image
                target.parent.mkdir(exist_ok=True)
                with Image.open(path) as image: image.convert("RGB").save(target)
            refs[shot["id"]] = relative
            self.store.update(pid, lambda p, sid=shot["id"], rel=relative: next(s for s in p["shots"] if s["id"] == sid).update(reference=rel))
        return refs

    def execute_shot(self, project, shot, role, reference, jid, cancel, retries, seed_offset=0, design=None):
        self.enter_stage(project["id"], jid, role, cancel)
        template = project["templates"][role]
        for attempt in range(retries + 1):
            if cancel.is_set():
                raise Cancelled("Cancelled")
            token = uuid.uuid4().hex[:16]
            context = {"project_id": project["id"], "shot_id": shot["id"], "role": role,
                       "spec": shot_spec(project, shot), "assets": project["assets"], "reference": reference,
                       "references": bound_references(project, design or shot),
                       "designs": [] if design else current_designs(project)}
            if design:
                context["spec"]["reference_prompt"] = design["prompt"] + "\nContinuity: " + project.get("bible", "")
            context["spec"]["seed"] = (context["spec"]["seed"] + seed_offset + attempt) % (2**63)
            path = self.store.asset(project["id"], f"contexts/{token}.json")
            path.parent.mkdir(exist_ok=True)
            path.write_text(json.dumps(context))
            graph = bind_template(template, project["id"], shot["id"], token)
            try:
                result = self.client.execute(graph, template["output_node"], role, cancel,
                    lambda prompt_id: self.progress(project["id"], jid, prompt_id=prompt_id, attempt=attempt + 1))
                if role == "video":
                    validate_clip(result, context["spec"])
                else:
                    from PIL import Image
                    with Image.open(result) as image:
                        image.verify()
                return result, {"seed": context["spec"]["seed"], "context_id": token, "template_hash": template["hash"]}
            except Cancelled:
                raise
            except Exception as exc:
                self.progress(project["id"], jid, last_attempt_error=str(exc))
                if attempt == retries:
                    raise
