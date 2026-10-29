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

## Version 0.2 additions

Automated checks cover exact user time ranges, explicit holds, bounded 10-minute tails,
ambiguous reference rejection, legacy scene-reference migration, selective reference hashes,
and mocked director output producing canonical sheets plus separate image/video prompts.
Reference-only scheduling generates sheets before camera frames, reuses both caches and
produces no video takes. HTTP tests upload multiple images and a silent depth video, edit
reference metadata, and load both bundled templates through the one-click endpoint.

The installer dry-run and workflow filename contract are validated locally. Actual large
weight downloads, system package installation, Ollama inference, and Runpod GPU renders have
not been executed here. Those require the target pod and model access. The 0.2 director's
creative quality is not established by the mocked-model tests.

The final 0.2 suite passes 36 tests, including the HTTP develop → sheet generation →
shot reference generation → edit/invalidation flow using mocked model responses.
JavaScript syntax and Python compilation pass. A fresh browser smoke test could not run
in this environment: Playwright's browser bundle is absent and the system Chrome process
exited during launch. The earlier browser checks above apply to 0.1; the new 0.2 panels
still need visual verification in the target ComfyUI browser.

## Version 0.3 canvas and GPU handoffs

45 automated tests pass, including generated canvas graph links/socket contracts, silent
project creation, stale asset rejection, read-only Codex command/schema construction,
explicit Ollama thinking, output-budget rejection, unload acknowledgement polling, cleanup
on errors, cancellation without global interruption, and cross-project job serialization.
The earlier 0.2 tests still pass. Python compilation, JavaScript syntax and diff whitespace
checks pass. Native ComfyUI/CUDA execution of the new canvas graphs remains untested here.

A real Codex CLI smoke test was attempted. It failed before model inference because the
sandbox could not initialize the local Codex state/app-server. The additional filesystem
permission was not granted. No successful live Codex reasoning or MCP model call is claimed.
The user chose to configure a direct GPT-6 Astra API integration manually; no API credential
was requested or saved and no API request was made. The Codex/MCP adapters remain optional.
