# Infinite Director

**Record once. Recast, redirect, and re-edit the scene.**

A ComfyUI custom node pack and scene editor that builds a cinematic edit from a
recorded performance, Qwen image references, and LTX 2.5 video generation. The
original audio defines the timeline. Shots, references, takes, and render settings
persist across sessions. Editing one shot does not require rebuilding the whole film.

## What is implemented

- A browser studio inside ComfyUI: projects, media uploads, storyboard, timeline,
  shot direction, cut boundaries, take selection, approval, and export.
- Studio bridge nodes plus standalone **Director**, chainable **Other Reference**, sheet/shot prompt nodes, take saving and timeline preview.
- Flat, editable Qwen Image Edit 2511 and LTX 2.5 audio-to-video workflows, plus
  corresponding API graphs. The bundled graphs use local model nodes only.
- A background scheduler that queues normal ComfyUI prompts, batches reference
  work before video work, reuses cached references/takes, and supports bounded retries.
- Separate candidate takes with distinct seeds and recorded provenance.
- Local vision director: timecoded direction → generated scene bible → Qwen character/prop sheets → camera opening frames and LTX motion prompts.
- Multiple image/video references with explicit roles and @reference bindings; preproduction audit panels.
- Optional local Ollama sparse visual observations and advisory take review.
- Optional local faster-whisper transcription, or timestamped transcript import.
- Frame-exact edit assembly using FFmpeg, a single master audio track, lossless WAV
  export, and an edit manifest. Existing generated speech is not used in the final edit.
- Recovery after restart: completed assets persist; interrupted jobs require explicit
  resume. Cancel never globally interrupts unrelated ComfyUI jobs.

**Validation status:** the core, HTTP API, media pipeline, and browser flow are tested
with synthetic media and a simulated renderer. Actual Qwen/LTX inference has not yet
been run on a GPU in this development environment. Model-specific quality, lip sync,
VRAM use, and inference speed remain unmeasured. See [VALIDATION.md](docs/VALIDATION.md).

## Install

1. Put this folder in `ComfyUI/custom_nodes/ComfyUI-Infinite-Director`, or symlink it there.
2. Use the Python environment that runs ComfyUI:

   ```bash
   python -m pip install -r custom_nodes/ComfyUI-Infinite-Director/requirements.txt
   ```

3. Install FFmpeg and FFprobe on that process's PATH. On macOS, `brew install ffmpeg`;
   on Ubuntu, `sudo apt install ffmpeg`. Windows portable installations also need the
   executables on PATH before launching ComfyUI.
4. Install/update ComfyUI and [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)
   to versions supporting the LTX 2.5 workflow nodes. Download the models below.
5. Restart ComfyUI and reload the browser. Open **Infinite Director** at the bottom left.

Alternatively, on Runpod, from this repository folder and in **ComfyUI's Python environment**:

```bash
python scripts/setup_runpod.py --comfy-root /workspace/ComfyUI --all
```

This installs dependencies and LTX nodes, installs FFmpeg when running as root on Ubuntu,
installs/starts Ollama, pulls `qwen3.6:27b-q8_0`, and downloads the eight exact model files used by
the bundled renderers. Use `--dry-run --all` to inspect destinations first. Downloads
resume, upstream revisions are recorded, and file sizes / available SHA-256 hashes are
verified. Existing matching weights are reused. Existing LTX checkout changes are preserved.
The installed Torch packages are constrained to their existing versions.

The full BF16 model set is large; the script checks remaining disk space from upstream
metadata. Use a persistent `/workspace` volume. Obtain access to
[LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) on Hugging Face first, then set `HF_TOKEN`
in the pod environment or log in with `hf auth login`. Tokens do not belong in the studio.
This installs into an existing instance; it does not provision or bill a new Runpod instance.
GPU rental and storage still cost money. See [Runpod setup](docs/RUNPOD.md).

Model downloads occur only when you explicitly run the setup script. The studio itself
uses local inference and does not download weights.
The scheduler connects to the same ComfyUI process over loopback HTTP using its configured
port. Reverse-proxy HTTPS is fine; direct TLS-only ComfyUI is not currently supported.

## Separate canvas workflow (0.3)

See [Canvas Director guide](docs/CANVAS_DIRECTOR.md). Load these in sequence:

1. `workflows/04-canvas-director.json`: images/videos + prompt → Director → bible, design prompts, shot instructions and project ID.
2. `workflows/05-canvas-qwen-sheets.json`: paste project ID → Qwen generates every character/prop sheet → save and preview.
3. `workflows/06-canvas-qwen-ltx-shot.json`: paste project ID, choose zero-based shot index → Qwen opening frame → LTX segment → saved take and timeline audit.

The canvas Director supports optional Codex CLI (`codex`), our stdio MCP bridge (`codex_mcp`),
and local Ollama. Codex is a hosted reasoner and sends selected text/images to its service;
it is not part of the fully local competition configuration. The local default is
`qwen3.6:27b-q8_0`, with thinking explicitly enabled. The hosted API integration can be
implemented manually at the documented provider boundary without giving a coding agent tools.

## First scene

1. **Create a scene** and upload a performance video containing picture and audio.
2. Optionally upload a character reference. Add multiple images or videos to **Other References**,
   assign their roles, and describe their intended use. Each has an `@ref_…` identifier.
3. Write **Direction** in ordinary language or explicit time ranges. Use reference IDs for
   phrases such as “inside the cup like this image.” Leave **Scene bible** blank to generate it,
   or enter fixed constraints: identity, wardrobe, set geography, lighting and props.
4. Choose **Use bundled Qwen + LTX renderers** after running setup. For custom model variants,
   load each graph, adjust its loaders/settings, and **Capture canvas** instead.
5. Optionally import a timestamped transcript and/or observe the performance.
6. Select your Ollama vision model (default `qwen3.6:27b-q8_0`) and choose
   **Develop scene → generate sheets & shots**. This saves Direction, inspects the references,
   builds the bible and design prompts, writes the shot plan, then queues Qwen sheets and
   opening frames. Explicit cut boundaries are preserved. Unspecified intervals become
   auditable holds; long intervals are subdivided into bounded renders.
7. Inspect **Preproduction audit**: bible, assumptions, character/prop sheets and prompts.
   Inspect each shot's opening frame, reference bindings, Qwen prompt and LTX prompt. Edit
   sheet prompts or shot prompts as needed; **Generate sheets & shot references** resumes
   preproduction without generating video. Changing upstream settings invalidates dependent takes.
8. **Render missing shots** generates LTX takes using original audio slices. **Render this shot**
   makes an alternate take with a different seed.
9. Watch and **Approve** each desired take. **Export approved scene** creates 1280×720 video,
   original PCM master audio, and an edit manifest. Every shot must have a current approved take.

The scene bible is a shared continuity record, not a technical prompt you must write yourself.
Example: “Same woman in a red cardigan throughout. White ceramic cup in her right hand.
Window on her left; counter behind her. Warm afternoon light. Cup stays half full.”
The agent turns that record into model-specific prompts. Generated hidden angles are invented,
not recovered from the source camera.

Other References videos are inspected through sparse frames and represented in Qwen's labeled
reference board. **Depth and pose are not hard LTX controls in the bundled workflow.** A custom
compatible control workflow is needed for that. Continuous motion reconstruction and reliable
lip sync are not guaranteed. Original dialogue timing is preserved by final audio assembly.

## Models and locations

The filenames below are the bundled loader defaults. Select the actual files you have
installed; quantized variants may use different names and memory characteristics.

| Location under `ComfyUI/models/` | Default file |
| --- | --- |
| `diffusion_models/` | `qwen_image_edit_2511_bf16.safetensors` |
| `text_encoders/` | `qwen_2.5_vl_7b_fp8_scaled.safetensors` |
| `vae/` | `qwen_image_vae.safetensors` |
| `diffusion_models/` | `ltx-2.5-22b-distilled-transformer-bf16.safetensors` |
| `text_encoders/` | `gemma4-12b-with-proj-ltx-2.5-bf16.safetensors` |
| `vae/` | `ltx-2.5-video-vae-bf16.safetensors` |
| `vae/` | `ltx-2.5-audio-vae-bf16.safetensors` |
| `latent_upscale_models/` | `ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors` |

Sources: [Qwen-Image](https://github.com/QwenLM/Qwen-Image),
[LTX-2.5 weights](https://huggingface.co/Lightricks/LTX-2.5),
[LTX workflow guide](https://github.com/Lightricks/ComfyUI-LTXVideo/tree/master/example_workflows/2.5).

The base Qwen graph uses multi-image editing with a canonical character sheet and a labeled board of selected references and prop sheets.
A compatible camera-angle LoRA may be inserted into the graph, with its required prompt
syntax. It is not required or silently downloaded. LTX runs at 960×544 then upscales 2×
by default. Reduce the latent dimensions for lower memory; both should remain divisible by 32.

## Local intelligence

**Director / visual reviewer:** run Ollama on the same host and enter a model already
listed by `ollama list`. A text model can direct; observation and review need a vision
model. The pack calls `/api/chat` with structured JSON, temperature 0.2, and `keep_alive: 0`
to release model memory afterward. Set `INFINITE_DIRECTOR_OLLAMA_URL` for a different
loopback port. Remote inference URLs are intentionally rejected.

**Transcription:** install `requirements-transcription.txt`, download a faster-whisper
model separately, and enter its local directory. The default implementation uses CPU
int8 inference and word timestamps. It never downloads weights on your behalf.

**Transcript import:** a JSON array, or an object with `segments`:

```json
[{"start": 0.2, "end": 2.8, "text": "I thought we had more time."}]
```

Times are seconds from the start of the original recording. Segments must be ordered,
finite, and within its duration. The transcript is planning data, not generated speech.

## How consistency works

The scene bible and canonical references are applied independently to each shot.
The director enriches fixed shot intervals; it cannot change timestamps. Manual cut
edits move one shared boundary, preserving coverage without gaps or overlaps.

Reference and video fingerprints include their dependencies. Camera/action/reference
changes invalidate the relevant shot. A scene-bible or model-template change can invalidate
many shots. Old takes remain on disk and can be reused if matching settings are restored.
Generated reference previews are cleared when their dependencies change. Uploaded shot
references remain explicit overrides until you choose **Use generated reference**.

Generation includes short handles and rounds up to legal LTX frame counts. Audio slices
use absolute frame-to-sample conversion, with zero padding only beyond the source. Assembly
normalizes video frame rate, trims the handles, and joins exact edit frame counts. It then
muxes the master audio once. MP4 uses AAC; the separate WAV preserves the prepared PCM master.

## Scope and limitations

This release implements **reference-conditioned audio-to-video coverage**. It does not
reconstruct a 3D performance, transfer exact gestures to unseen angles, or provide a
pose/depth/video-to-video route. Continuous visual extension across long same-angle shots
is not implemented; planned shots are independently generated camera setups. Explicit
camera cuts are the intended presentation.

Automatic checks verify output type and usable duration. Optional vision review examines
three still frames and is advisory. It does not measure lip sync or guarantee temporal
consistency. Failed technical renders retry within a bound; visual defects need a new take
or revised shot/reference. There is no hidden automatic replacement of difficult shots.

Project limits: up to one hour of source video, 2 GiB upload, 40 megapixels per image.
The UI defaults to 24 fps. Long source files should be normalized before upload if needed.
Cancel removes a pending Director prompt only; an already-running GPU prompt or local model
call may finish. Completed work is retained. Review the Comfy queue before resuming after a crash.

Imported templates are checked against installed node metadata for partner/API nodes.
That is not a security audit of third-party code. For the open-weights competition category,
keep the bundled local paths and review any additional custom nodes you introduce.

## Storage and development

Projects are stored in `ComfyUI/output/infinite_director/<project-id>/`. Override with
`INFINITE_DIRECTOR_HOME` before starting ComfyUI. The folder contains source assets,
`project.json`, immutable render contexts, cached references, takes, and exports.
Back up the whole directory to retain a project. Source replacements preserve old files.
This is a local single-process studio, not a multi-tenant service.

Run CPU tests from this repository using an environment with the base requirements:

```bash
python -m unittest discover -s tests -v
node --check web/director.js
```

Rebuild bundled workflows after editing their generator:

```bash
python scripts/build_workflows.py
```

For a standalone UI test without ComfyUI, `python tests/harness.py --root /tmp/director-test`
(with this repository on `PYTHONPATH`) serves port 8199. Its render outputs are explicitly
synthetic test fixtures. It is never loaded by the production plugin.

See [architecture](docs/ARCHITECTURE.md), [validation](docs/VALIDATION.md), and
[competition demo guide](docs/COMPETITION.md). App code: MIT. Attributed LTX workflow
adaptation and external models retain their own licenses; see [notices](THIRD_PARTY_NOTICES.md).
