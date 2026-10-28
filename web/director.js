import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const BASE = "/infinite-director";
const cameraNames = { front: "Front / medium", three_quarter: "Three-quarter / close", profile: "Left profile", wide: "Wide / establishing", detail: "Hands & prop insert", cup_pov: "Inside the cup" };
const css = document.createElement("link");
css.rel = "stylesheet"; css.href = new URL("./director.css", import.meta.url).href; document.head.append(css);

function el(tag, cls, text) { const node = document.createElement(tag); if (cls) node.className = cls; if (text != null) node.textContent = text; return node; }
function button(text, fn, cls = "id-button") { const b = el("button", cls, text); b.type = "button"; b.onclick = fn; return b; }
function field(label, value, multiline = false) { const wrap = el("label", "id-field"); wrap.append(el("span", "", label)); const input = el(multiline ? "textarea" : "input"); input.value = value ?? ""; if (multiline) input.rows = 3; wrap.append(input); return { wrap, input }; }
function time(frame, fps) { const sec = frame / fps; return `${Math.floor(sec / 60)}:${(sec % 60).toFixed(2).padStart(5, "0")}`; }
async function request(path, data, method = "POST") {
    const options = data === undefined ? {} : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) };
    const response = await api.fetchApi(BASE + path, options);
    const body = await response.json(); if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`); return body;
}

function ask(message, initial = null) {
    return new Promise(resolve => {
        const modal = el("dialog", "id-confirm"); const form = el("form"); form.method = "dialog";
        form.append(el("p", "", message)); let input;
        if (initial !== null) { input = el("input"); input.value = initial; input.setAttribute("aria-label", message); form.append(input); }
        const row = el("div", "id-actions"); const cancel = button("Cancel", () => modal.close("cancel"));
        const accept = el("button", "id-button id-primary", initial !== null ? "Save" : "Continue"); accept.type = "submit"; accept.value = "accept";
        row.append(cancel, accept); form.append(row); modal.append(form); document.body.append(modal);
        modal.addEventListener("close", () => { const result = modal.returnValue === "accept" ? (input ? input.value : true) : null; modal.remove(); resolve(result); }, {once:true});
        modal.showModal(); if (input) { input.focus(); input.select(); }
    });
}

class Director {
    constructor() { this.project = null; this.selected = null; this.opened = false; this.timer = null; this.runningAction = false; }
    async open() {
        if (this.opened) return;
        this.opened = true;
        this.overlay = el("div", "id-overlay"); this.overlay.setAttribute("role", "dialog"); this.overlay.setAttribute("aria-label", "Infinite Director scene editor");
        this.overlay.setAttribute("aria-modal", "true"); this.overlay.tabIndex = -1;
        this.keyHandler = (event) => {
            if (event.key === "Escape") this.close();
            if (event.key === "Tab") {
                const items = [...this.overlay.querySelectorAll('button,input,textarea,select,a[href]')].filter(n => !n.disabled && n.offsetParent !== null);
                if (!items.length) return;
                if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1).focus(); }
                else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0].focus(); }
            }
        };
        this.overlay.addEventListener("keydown", this.keyHandler);
        const header = el("header", "id-header"); const brand = el("div", "id-brand");
        brand.append(el("span", "id-mark", "ID"), el("div", "", "INFINITE DIRECTOR"), el("span", "id-beta", "LOCAL STUDIO"));
        header.append(brand, button("Back to canvas ↗", () => this.close(), "id-button id-ghost"));
        const layout = el("div", "id-layout"); this.sidebar = el("aside", "id-sidebar"); this.main = el("main", "id-main");
        layout.append(this.sidebar, this.main); this.status = el("div", "id-status", "Ready"); this.status.setAttribute("role", "status");
        this.overlay.append(header, layout, this.status); document.body.append(this.overlay); this.overlay.focus();
        await this.guard(async () => { await this.refreshProjects(); const saved = localStorage.getItem("infinite-director-project"); if (saved) await this.load(saved); else this.empty(); });
        this.timer = setInterval(() => this.poll(), 2000);
    }
    close() { this.opened = false; clearInterval(this.timer); this.overlay?.remove(); }
    async guard(fn) { if (this.runningAction) return; this.runningAction = true; try { await fn(); } catch (e) { this.message(e.message, true); } finally { this.runningAction = false; } }
    message(text, error = false) { if (!this.status) return; this.status.textContent = text; this.status.classList.toggle("id-error", error); }
    path(suffix = "") { return `/projects/${this.project.id}${suffix}`; }
    media(file) { return api.apiURL(BASE + this.path(`/media?file=${encodeURIComponent(file)}`)); }
    async refreshProjects() {
        const projects = await request("/projects"); this.sidebar.replaceChildren();
        this.sidebar.append(el("div", "id-eyebrow", "YOUR SCENES"), button("＋ New scene", () => this.newScene(), "id-button id-primary"));
        for (const p of projects) { const b = button(p.name, () => this.guard(() => this.load(p.id)), "id-project"); b.classList.toggle("active", p.id === this.project?.id); this.sidebar.append(b); }
        const footer = el("div", "id-sidebar-footer"); footer.append(el("strong", "", "Record once."), el("p", "", "Recast. Redirect. Re-edit."), el("small", "", "Qwen references · LTX video\nOriginal performance audio")); this.sidebar.append(footer);
    }
    empty() { this.main.replaceChildren(); const box = el("div", "id-welcome"); box.append(el("div", "id-eyebrow", "YOUR PERFORMANCE. EVERY ANGLE."), el("h1", "", "One take.\nA whole scene."), el("p", "", "Bring your recording and a character. Build the camera coverage, direct each beat, and keep the voice that made it yours."), button("Create a scene →", () => this.newScene(), "id-button id-primary")); this.main.append(box); }
    async newScene() { const name = await ask("Scene name", "The café conversation"); if (!name) return; this.guard(async () => { const p = await request("/projects", { name, fps: 24 }); await this.load(p.id); await this.refreshProjects(); }); }
    async load(id) { this.project = await request(`/projects/${id}`); localStorage.setItem("infinite-director-project", id); if (!this.project.shots.some(s => s.id === this.selected)) this.selected = this.project.shots[0]?.id; this.render(); }
    async poll() { if (!this.opened || !this.project || this.runningAction || this.polling) return; this.polling = true; try {
        const p = await request(this.path()); const job = p.jobs.at(-1);
        if (job) this.message(`${job.kind} · ${job.status}${job.phase ? ` · ${job.phase}` : ""}${job.shot ? ` · ${job.shot}` : ""}${job.error ? ` — ${job.error}` : ""}`, job.status === "failed");
        if (p.revision !== this.project.revision || p.busy !== this.project.busy) {
            const editing = this.overlay.contains(document.activeElement) && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
            // Preserve draft fields AND their old revision. Saving will surface a conflict rather than overwrite another edit.
            if (!editing) { this.project = p; this.render(); }
        }
    } catch (e) { this.message(e.message, true); } finally { this.polling = false; } }
    async mutate(suffix, data = {}, method = "POST") { await request(this.path(suffix), data, method); await this.load(this.project.id); }
    upload(kind, shotId) {
        const input = el("input"); input.type = "file"; input.accept = kind === "source" ? "video/*" : "image/*";
        input.onchange = () => this.guard(async () => {
            if (!input.files[0]) return;
            this.message("Uploading and preparing media…"); const form = new FormData(); form.append("file", input.files[0]);
            const res = await api.fetchApi(BASE + this.path(`/assets/${kind}`) + (shotId ? `?shot_id=${encodeURIComponent(shotId)}` : ""), { method: "POST", body: form });
            const body = await res.json(); if (!res.ok) throw new Error(body.error); await this.load(this.project.id); this.message("Asset ready");
        }); input.click();
    }
    render() {
        if (!this.opened) return;
        const p = this.project; this.main.replaceChildren();
        const top = el("div", "id-title-row"); const title = el("div"); title.append(el("div", "id-eyebrow", "SCENE WORKSPACE"), el("h1", "", p.name));
        const stats = el("div", "id-stats", `${p.shots.length} shots  /  ${time(p.total_frames, p.fps)}  /  ${p.fps} fps`); top.append(title, stats); this.main.append(top);
        const actions = el("div", "id-actions");
        actions.append(button("Render missing shots", () => this.guard(() => this.mutate("/render", { retries: 1 })), "id-button id-primary"),
            button("Export approved scene", () => this.guard(() => this.mutate("/export", { width: 1280, height: 720 }))),
            button("Refresh", () => this.guard(() => this.load(p.id)), "id-button id-ghost"));
        if (p.busy) actions.append(button("Cancel operation", () => this.guard(() => this.mutate("/cancel")), "id-button id-danger"));
        this.main.append(actions);
        const setup = el("details", "id-setup"); setup.open = !p.shots.length; setup.append(el("summary", "", "01  /  Performance, references & renderers"));
        const assets = el("div", "id-assets");
        for (const [kind, label] of [["source", "Performance video"], ["character", "Character reference"], ["scene", "Scene reference"]]) {
            const card = el("div", "id-asset"); const asset = p.assets[kind];
            if (asset) { const img = el("img"); img.src = this.media(asset.poster || asset.file); img.alt = label; card.append(img); }
            else card.append(el("div", "id-asset-placeholder", kind === "source" ? "▶" : "＋"));
            card.append(el("strong", "", label), button(asset ? "Replace" : "Upload", async () => { if (kind === "source" && p.shots.length && !await ask("Replacing the performance clears the active plan and transcript. Existing media files remain on disk. Continue?")) return; this.upload(kind); }, "id-button id-ghost")); assets.append(card);
        }
        setup.append(assets);
        const fields = el("div", "id-two-col"); const bible = field("Scene bible · identity, wardrobe, geography, props", p.bible, true); const direction = field("Direction · tone, camera language, special shots", p.direction, true); fields.append(bible.wrap, direction.wrap); setup.append(fields);
        setup.append(button("Save direction", () => this.guard(() => this.mutate("", { bible: bible.input.value, direction: direction.input.value, revision: p.revision }, "PATCH"))));
        const renderers = el("div", "id-renderers");
        for (const [role, file, label] of [["reference", "02-qwen-reference.json", "Qwen · reference renderer"], ["video", "03-ltx25-audio-video.json", "LTX 2.5 · video renderer"]]) {
            const row = el("div", "id-renderer"); row.append(el("strong", "", label), el("span", p.templates[role] ? "id-ready" : "id-muted", p.templates[role] ? "Captured" : "Not configured"),
                button("Load graph", () => this.guard(async () => {
                    if (!await ask("Load the bundled workflow onto the canvas? Save any unsaved canvas work first.")) return;
                    const wf = await request(`/workflows/${file}`);
                    for (const node of wf.nodes) if (node.type === "IDShotInputs") node.widgets_values = [p.id, this.selected || "shot_0001", ""];
                    await app.loadGraphData(wf); this.close();
                }), "id-button id-ghost"),
                button("Capture canvas", () => this.guard(async () => { const prompt = await app.graphToPrompt(); await this.mutate(`/templates/${role}`, { graph: prompt.output, revision: p.revision }); this.message(`${label} saved. Model settings are now frozen for this project.`); })));
            renderers.append(row);
        }
        setup.append(renderers, el("p", "id-help", "Load each graph, select installed model files, then reopen this studio and capture the canvas. Shot Inputs connects the timeline to both renderers. No paid API nodes are included."));
        const intelligence = el("div", "id-intelligence"); const model = field("Installed Ollama model (director / vision)", localStorage.getItem("id-ollama-model") || ""); model.input.placeholder = "Name from ollama list";
        const runAI = action => this.guard(async () => { localStorage.setItem("id-ollama-model", model.input.value); await this.mutate("/intelligence", { action, model: model.input.value }); });
        intelligence.append(model.wrap, button("Direct existing shots", () => runAI("direct")), button("Observe performance", () => runAI("observe")), button("Import transcript", () => this.importTranscript()), button("Transcribe locally", async () => { const path = await ask("Absolute path to an installed faster-whisper model directory", ""); if (path) this.guard(() => this.mutate("/intelligence", { action: "transcribe", model: path })); }));
        setup.append(intelligence);
        const planRow = el("div", "id-actions"); const seconds = field("Target shot duration", "6"); seconds.input.type = "number"; seconds.input.min = 2; seconds.input.max = 12;
        planRow.append(seconds.wrap, button(p.shots.length ? "Rebuild shot plan" : "Plan scene →", async () => {
            if (p.shots.length && !await ask("Replace the active shot plan? The previous plan is preserved in the manifest history.")) return;
            this.guard(() => this.mutate("/plan", { target_seconds: Number(seconds.input.value), replace: !!p.shots.length, revision: p.revision }));
        }, "id-button id-primary"), el("span", "id-muted", `${p.transcript.length} transcript segments · ${p.observations?.length || 0} visual observations`)); setup.append(planRow); this.main.append(setup);
        if (p.shots.length) this.renderTimeline();
        if (p.export) {
            const box = el("section", "id-export"); box.append(el("div", "id-eyebrow", "FINISHED SCENE")); const video = el("video"); video.controls = true; video.src = this.media(p.export.file); box.append(video);
            for (const [label, file] of [["Download video", p.export.file], ["Lossless master audio", p.export.master]]) { const a = el("a", "id-button", label); a.href = this.media(file); a.download = file.split("/").at(-1); box.append(a); }
            this.main.append(box);
        }
        const foot = el("div", "id-actions"); const manifest = el("a", "id-muted", "Download scene manifest ↗"); manifest.href = api.apiURL(BASE + this.path("/manifest")); manifest.download = "scene-manifest.json"; foot.append(manifest); this.main.append(foot);
        if (p.busy) this.main.querySelectorAll("button").forEach(b => { if (!["Cancel operation", "Refresh"].includes(b.textContent)) b.disabled = true; });
    }
    importTranscript() { const input = el("input"); input.type = "file"; input.accept = ".json"; input.onchange = () => this.guard(async () => { const raw = JSON.parse(await input.files[0].text()); await this.mutate("/transcript", { segments: Array.isArray(raw) ? raw : raw.segments, revision: this.project.revision }); }); input.click(); }
    renderTimeline() {
        const p = this.project;
        const section = el("section", "id-edit"); const head = el("div", "id-section-title"); head.append(el("div", "id-eyebrow", "02  /  THE EDIT"), el("span", "id-muted", `${p.shots.filter(s => s.status === "approved").length}/${p.shots.length} approved`)); section.append(head);
        const strip = el("div", "id-shot-strip");
        p.shots.forEach((s, i) => { const b = button("", () => { this.selected = s.id; this.render(); }, `id-shot ${s.id === this.selected ? "selected" : ""}`);
            const image = s.reference_override?.file || s.reference;
            if (image) { const img = el("img"); img.src = this.media(image); img.alt = cameraNames[s.camera]; b.append(img); }
            else b.append(el("div", "id-shot-placeholder", String(i+1).padStart(2, "0")));
            const line = el("div", "id-shot-caption"); line.append(el("strong", "", `${String(i+1).padStart(2, "0")}  ${cameraNames[s.camera]}`), el("span", "", `${time(s.start,p.fps)} — ${time(s.end,p.fps)}`), el("span", `id-tag ${s.status}`, s.status)); b.append(line); strip.append(b);
        }); section.append(strip);
        const track = el("div", "id-timeline"); track.setAttribute("aria-label", "Shot durations on the original audio timeline");
        p.shots.forEach((s,i) => { const block = button(String(i+1).padStart(2,"0"), () => { this.selected=s.id; this.render(); }, `id-segment ${s.id===this.selected?"selected":""}`); block.style.flex = String(s.end-s.start); block.title = `${s.id}: ${time(s.start,p.fps)} – ${time(s.end,p.fps)}`; track.append(block); }); section.append(track);
        const audio = el("audio"); audio.controls = true; audio.src = this.media(p.assets.source.audio); audio.preload = "metadata"; section.append(audio);
        const shot = p.shots.find(s => s.id === this.selected) || p.shots[0]; this.selected = shot.id;
        const editor = el("div", "id-shot-editor"); const preview = el("div", "id-preview");
        const take = shot.candidates.find(c => c.id === shot.selected);
        if (take) { const video = el("video"); video.controls = true; video.src = this.media(take.file); video.preload = "metadata"; preview.append(video); preview.append(el("p", "id-help", "Take preview includes generation handles. Final export trims to the edit and uses the original master audio.")); }
        else if (shot.reference_override?.file || shot.reference) { const img = el("img"); img.src = this.media(shot.reference_override?.file || shot.reference); img.alt = "Selected shot reference"; preview.append(img); }
        else { const placeholder = el("div", "id-preview-empty"); placeholder.append(el("span", "", "FRAME / " + shot.id.split("_").at(-1)), el("p", "", "Your next camera angle starts here.")); preview.append(placeholder); }
        const takeRow = el("div", "id-actions");
        takeRow.append(button("Render this shot", () => this.guard(() => this.mutate("/render", { shot_ids:[shot.id], retries:1, force:true })), "id-button id-primary"), button("Upload shot reference", () => this.upload("reference",shot.id), "id-button id-ghost"));
        if (shot.reference_override) takeRow.append(button("Use generated reference", () => this.guard(() => this.mutate(`/shots/${shot.id}`, {clear_reference:true,revision:p.revision},"PATCH")), "id-button id-ghost"));
        preview.append(takeRow);
        if (shot.candidates.length) {
            const takes = el("div", "id-takes"); takes.append(el("div", "id-eyebrow", "TAKES · REVIEW BEFORE APPROVING"));
            shot.candidates.forEach((c,i) => { const row=el("div","id-take"); row.append(el("span","",`Take ${i+1}${c.id===shot.selected?" · selected":""}${c.approved?" · approved":""}`),button("Select",()=>this.guard(()=>this.mutate(`/shots/${shot.id}/select`,{candidate_id:c.id,approved:false,revision:p.revision})),"id-button id-ghost"),button("Approve",()=>this.guard(()=>this.mutate(`/shots/${shot.id}/select`,{candidate_id:c.id,approved:true,revision:p.revision})),"id-button")); takes.append(row); }); preview.append(takes);
            preview.append(button("Review with local vision model", () => this.guard(() => this.mutate("/intelligence", {action:"review", shot_id:shot.id, model:localStorage.getItem("id-ollama-model") || ""})), "id-button id-ghost"));
            if (take?.visual_review) { const review = el("details", "id-setup"); review.append(el("summary", "", "Vision review · advisory only"), el("pre", "id-review-text", JSON.stringify(take.visual_review.assessment, null, 2))); preview.append(review); }
            preview.append(el("p","id-help","Technical checks verify duration and decodability. Identity, hands, action continuity, and lip sync require your visual review. Stale takes cannot be selected."));
        }
        const form=el("div","id-shot-form"); form.append(el("div","id-eyebrow",`${shot.id.toUpperCase()} · ${time(shot.start,p.fps)} → ${time(shot.end,p.fps)}`));
        const camWrap=el("label","id-field"); camWrap.append(el("span","","Camera")); const camera=el("select"); for(const [key,label] of Object.entries(cameraNames)){const option=el("option","",label);option.value=key;option.selected=key===shot.camera;camera.append(option);} camWrap.append(camera);form.append(camWrap);
        const fields={};for(const [key,label] of [["purpose","Purpose"],["action","Action / performance"],["state_in","State at start"],["state_out","State at end"],["notes","Additional direction"]]){fields[key]=field(label,shot[key],key!=="purpose");form.append(fields[key].wrap);}
        const seed=field("Seed",shot.seed);seed.input.type="number";seed.input.min="0";form.append(seed.wrap);
        form.append(button("Save shot direction",()=>this.guard(()=>this.mutate(`/shots/${shot.id}`,{camera:camera.value,seed:Number(seed.input.value),...Object.fromEntries(Object.entries(fields).map(([k,v])=>[k,v.input.value])),revision:p.revision},"PATCH")),"id-button id-primary"));
        if(shot!==p.shots.at(-1)){const end=field("Cut after this frame (exclusive)",shot.end);end.input.type="number";form.append(end.wrap,button("Move cut",()=>this.guard(()=>this.mutate("/boundary",{shot_id:shot.id,frame:Number(end.input.value),revision:p.revision})),"id-button id-ghost"));}
        const text=p.transcript.filter(s=>s.end>shot.start/p.fps&&s.start<shot.end/p.fps).map(s=>s.text).join(" ");if(text)form.append(el("blockquote","id-dialogue",text));
        editor.append(preview,form);section.append(editor);this.main.append(section);
    }
}

const director = new Director();
app.registerExtension({
    name: "InfiniteDirector.Studio",
    async setup() {
        const launcher = button("◉ Infinite Director", () => director.open(), "id-launcher");
        launcher.title="Open the Infinite Director scene editor"; document.body.append(launcher);
    },
    async nodeCreated(node) {
        if (["IDShotInputs","IDScenePlan","IDExportScene"].includes(node.comfyClass)) {
            node.addWidget("button", "Open Director Studio", null, () => director.open(), { serialize:false });
        }
    }
});
