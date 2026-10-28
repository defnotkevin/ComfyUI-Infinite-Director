# Validation record

Development environment: macOS, Python 3.13, FFmpeg/FFprobe, a temporary Python environment
with NumPy, Pillow, and aiohttp. Model weights were not installed. No GPU inference was run.

## Automated tests

Run from the repository: `python -m unittest discover -s tests -v`.

The suite covers:

- Exact frame coverage for short and 5–10 minute plans, including `8n+1` render padding.
- Speech-boundary preference; rejection of gaps, overlaps, NaN, and invalid timestamps.
- Dependency fingerprints, selective invalidation, and restored-setting reuse.
- Project path traversal rejection and revision-conflict handling.
- Bundled workflow link consistency, bridge binding, and partner-node rejection.
- Local-only model endpoint validation and immutable LLM cut timing.
- PCM audio slicing and padding verified against original sample arrays.
- Real FFmpeg export with exact frame count and a byte-identical copied WAV master.
- Rejection of undersized renders and stale/unapproved takes.
- Synthetic renderer scheduling, cache reuse, distinct alternate-take seeds, and restart recovery.
- Cancellation limited to the worker's own pending ComfyUI prompt.
- HTTP API plan preconditions, revision checks, transcript validation, and atomic cut edits.
- Manifest export retains full templates while normal editor reads omit their large graphs.

`node --check web/director.js` validates JavaScript syntax. Python sources are compiled
with `compileall`. Workflow generation is deterministic and the generated graphs are
included as editable JSON plus API-format JSON.

## Browser checks

The application was inspected in the in-app browser against `tests/harness.py`. Native
browser prompt dialogs were found unsupported there and replaced with HTML dialogs.
Scene creation, performance import, direction persistence, planning, and capturing the
bundled reference/video templates were exercised through the studio. Synthetic render
queue completion, take approval, real FFmpeg export, and selective invalidation after a
camera edit also passed in the browser. The harness uses
synthetic media and a simulated inference client; it cannot validate ComfyUI's real graph
serialization, model loading, or output quality.

## Outstanding model-host validation

- Load the two workflows into a current ComfyUI + ComfyUI-LTXVideo installation and
  verify node versions, available model filenames, and native graph serialization.
- Execute actual Qwen and LTX inference. Check identity, hands, scene geography,
  mouth motion, frame dimensions, and generated motion across camera cuts.
- Measure hardware-specific VRAM, elapsed time, and retry cost.
- Exercise Ollama text/vision inference and faster-whisper with installed model weights.

The software does not claim reconstructed 3D gestures, measured lip-sync quality,
continuous long-take extension, or validated five-minute generative output.
