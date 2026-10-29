# Architecture

## Project, plan, reference, take

A project owns immutable uploaded assets and an atomically replaced `project.json`.
Shots use integer start/end frames on a fixed frame-rate timeline; end is exclusive.
A shared boundary is edited as one operation on both adjacent shots. Validation runs
before persistence, so a rejected change does not partly mutate the file.

The reference key includes its compiled still prompt, canonical assets, reference
renderer snapshot, and seed. The render key includes the full shot specification,
reference dependencies or override, source audio asset, and video renderer snapshot.
Candidate takes retain their own dependency key and actual sampling seed. Approval
is attached to a candidate. An edit can make a candidate stale without deleting it.

Store locks serialize writes within one process. HTTP edits use optimistic revision
checks to reject overwriting changes made elsewhere. Editing is blocked while a
project has an active worker. This is not a distributed database or multi-tenant server.

## Rendering

The browser captures `app.graphToPrompt().output`. The graph must contain exactly one
`IDShotInputs` and an output reachable from it. Known partner/API nodes are rejected
using the installed ComfyUI node metadata. Imported custom Python node behavior is
outside that inspection's guarantees.

A worker first generates missing still references and then videos. For each task it
writes an immutable JSON context containing the source asset paths, exact audio window,
legal frame count, prompts, and seed. It replaces only the bridge inputs in a copy of
the saved API graph, submits `/prompt`, and polls `/history/<prompt-id>`.

The scheduler is outside ComfyUI's node execution loop, avoiding a node that waits
for a nested prompt behind itself in the GPU queue. Generated artifacts are copied
from ComfyUI output/temp into the project. Image validity and usable video duration
are checked before a candidate is recorded. No GPU model is loaded by the scheduler.

Reference generation uses Qwen Image Edit Plus with a canonical character input and a labeled board of selected references/prop designs.
Video generation uses LTX A2V with a first-frame reference and frozen supplied audio
latents. The final video output reuses the supplied audio. The later scene export
ignores those per-clip audio streams and muxes the master timeline once.

## Audio and boundaries

For a shot `[start,end)`, `render_start` includes a short preceding handle when available.
The render frame count is rounded **up** to `8n+1` so the retained edit never exceeds
the generated clip. Audio is sliced at sample indices calculated from absolute frames.
It is padded only where a requested generation window extends beyond the master.

The exporter normalizes each take to project fps, trims its handle and exact edit
frame count, scales with letterboxing, and concatenates picture. It then adds the
master waveform once. MP4 audio is AAC; the separately exported WAV is lossless PCM.
The export manifest records each original frame interval and take trim offset.

## Local intelligence

Ollama is optional and limited to loopback HTTP. Directing operates on batches of
12 fixed shots, carries the last scene state forward, and cannot alter cut times.
An invalid response fails the whole operation without applying a partial plan.
Sparse observation examines at most 40 performance stills. Take review compares
one reference with three sampled generated frames. Neither is motion capture or
measured lip-sync evaluation. Human approval remains mandatory for export.

## Operational behavior

- Render retries: 0–3, a new seed per retry. Explicit new takes also change the seed.
- Pending cancellation: deletes only the worker's prompt ID from the Comfy queue.
- Running cancellation: leaves unrelated GPU work alone; an already-running prompt
  may finish without being attached as a take. Resume after it completes.
- Restart: queued/running jobs become interrupted; matching completed assets are reused.
- Export cancellation: FFmpeg may finish its current operation; cancelled exports are
  not installed as the active export.
- Slow operations run off the aiohttp request loop.
- No publishing, telemetry, or credential storage is included. The explicit Runpod installer downloads verified weights; the studio itself never downloads models.


## Preproduction agent (0.2)

`direction.py` owns time boundaries, reference bindings and legacy scene migration. Explicit
ranges cannot be changed by the LLM. Missing intervals become hold shots; long spans are split
into bounded renders. `develop_scene` performs local vision inspection, continuity/design
planning, then bounded batches of shot prompts. It validates every shot ID, camera enum,
reference ID and prompt before committing the plan. A failed model response does not commit
a partial plan. Subsequent Qwen generation can be resumed from sheet/reference caches.

Design keys include the bible, source identity, selected references, renderer and seed.
Shot reference keys include current design keys. Changing a canonical sheet therefore
invalidates its dependent references and takes. Generated design images become the identity
input and prop board for later Qwen camera-frame renders. LTX consumes those camera frames
and the matching original audio slice. Video references are sampled for planning; the
bundled graph does not implement a depth/pose video-control adapter.

The installer keeps CUDA package versions constrained, preflights gated model access and
free disk, pins each resolved download revision, and verifies size/SHA-256 where available.
It preserves existing mismatching files and existing LTX checkouts rather than replacing them.
