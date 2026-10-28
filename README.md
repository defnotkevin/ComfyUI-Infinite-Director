# Infinite Director

**Record once. Recast, redirect, and re-edit the scene.**

A ComfyUI custom node pack and scene editor that builds a cinematic edit from a
recorded performance, Qwen image references, and LTX 2.5 video generation. The
original audio defines the timeline. Shots, references, takes, and render settings
persist across sessions. Editing one shot does not require rebuilding the whole film.

## What is implemented

- A browser studio inside ComfyUI: projects, media uploads, storyboard, timeline,
  shot direction, cut boundaries, take selection, approval, and export.
- Four custom nodes: **Shot Inputs**, **Scene Plan**, **LTX Frame Count**, **Export Scene**.
- Flat, editable Qwen Image Edit 2511 and LTX 2.5 audio-to-video workflows, plus
  corresponding API graphs. The bundled graphs use local model nodes only.
- A background scheduler that queues normal ComfyUI prompts, batches reference
  work before video work, reuses cached references/takes, and supports bounded retries.
- Separate candidate takes with distinct seeds and recorded provenance.
- Optional local Ollama directing, sparse visual observations, and advisory take review.
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

No weights are automatically downloaded and no API keys are required by this pack.
The scheduler connects to the same ComfyUI process over loopback HTTP using its configured
port. Reverse-proxy HTTPS is fine; direct TLS-only ComfyUI is not currently supported.

## First scene

1. **Create a scene** and upload a video containing both picture and audio.
2. Add a character image and optional scene reference. Without these, the recording's
   first frame is used as the corresponding reference.
3. Write the scene bible (identity, clothing, room, lighting, props) and direction. Save.
4. Import a transcript or transcribe locally; this is optional but improves edit planning.
5. **Plan scene**. Initial cuts target six seconds and prefer nearby speech boundaries.
6. Under **Qwen · reference renderer**, load the graph. Select your installed model files
   in its loaders. Reopen the studio and **Capture canvas** for the reference renderer.
7. Do the same for **LTX 2.5 · video renderer**. Set generation resolution and model variants
   on the canvas before capturing. Capture saves a snapshot, not a live link to the canvas.
8. Optionally supply an installed Ollama model and choose **Direct existing shots**.
9. **Render missing shots**. Watch progress in the status bar. Existing matching takes are
   reused; **Render this shot** deliberately creates a new take with a different seed.
10. Watch each take and **Approve** the desired candidate. Export requires every active
    shot to have an approved take matching current settings.
11. **Export approved scene** creates 1280×720 video, the original PCM master, and an edit
    manifest. The Export Scene node supports other even dimensions up to 4096.

The canvas graphs can also run manually: fill in `project_id` and `shot_id` on Shot Inputs
and leave `job_id` blank. Automated rendering supplies immutable context IDs itself.
Manual canvas output is not automatically attached as a scene take.

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

The base Qwen graph uses multi-image editing with character and scene references.
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
