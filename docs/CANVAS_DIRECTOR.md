# Node-based Director workflow

The three workflows are independent of the studio's template-capture workflow. They share
its persisted projects, frame timing, master audio, references and take review.

## 1. Plan: 04-canvas-director.json

Load character and performance media, then attach other images/videos through chained
**Other Reference** nodes. Each node accepts exactly one IMAGE or VIDEO plus the previous
reference bundle. Chain order gives predictable IDs (`@ref_001`, `@ref_002`, …). Label every
asset and choose a role; depth/pose videos are sampled evidence, not hard video controls.
The example includes a depth-video loader: disconnect/delete it if unused and connect the
first reference node directly to Director. Select actual files in all remaining loaders.

Director accepts name, direction, optional continuity constraints, provider/model, fps,
duration, and revision. Performance video supplies duration and original audio. Without a
performance, duration supplies the timeline and a silent master is created. An optional
character image anchors identity. Increment revision to create a fresh plan; do not rerun
planning just to render another shot. Copy the resulting project ID into later graphs.

Outputs are typed plan, project ID, scene bible, Qwen design prompt JSON, shot-segment JSON
(including compiled Qwen/LTX prompts), and full project JSON. The node shows a read-only
text audit. Invalid IDs/timings or incomplete model responses fail before committing a plan.
Failed planning can leave an input-only project so media is recoverable.

Provider choices:
- `ollama`: local model, default `qwen3.6:27b-q8_0`, explicitly requests thinking.
- `codex`: signed-in Codex CLI, JSON schema constrained output, high reasoning, read-only
  sandbox, ephemeral invocation, shell/apps disabled, no inherited user configuration.
- `codex_mcp`: same reasoner via **our** stdio MCP bridge, not the removed native Codex
  `mcp-server` command. Install `requirements-director.txt`. This is a local stdio process,
  not a publicly exposed TCP server. The Codex executable and authentication must exist on
  the ComfyUI host, not just on a laptop using its web interface.

Codex sends the supplied text/images to the service and uses account allowance/billing.
No credentials are stored in workflow JSON. An empty Codex model field uses the service
CLI default; specify an available Codex model ID only if deliberately overriding it.
Claude Code is not implemented as a provider in this version. The MCP protocol alone does
not make another agent's tool contract compatible with this Director's JSON contract.

## 2. Sheets: 05-canvas-qwen-sheets.json

Paste the project ID into Load Plan. Design Sheet Prompts emits synchronized ComfyUI lists:
Qwen prompt, identity image, labeled reference board, seed, filename and design task. Native
Qwen nodes map over the lists to render all character/prop sheets. Save Design Sheet registers
each canonical image; PreviewImage shows them. Review these in the studio before continuing.
The task is never manually paired by list position outside ComfyUI's list mapping.

## 3. Shot: 06-canvas-qwen-ltx-shot.json

Paste the project ID and choose a zero-based shot index. Current sheets must exist. Qwen
creates one opening frame using the canonical character and prop boards; Save Shot Reference
registers it. LTX Shot Segment releases Qwen weights and outputs motion prompt, frame, exact
source audio slice, fps, legal frame count, seed and take metadata. Native LTX renders one
segment. SaveVideo provides a canvas video preview; Save Take for Review also saves the
canonical project take. This means two video files may exist (preview and project copy).

Open Infinite Director Studio and choose the project to compare/approve takes and export.
Timeline Preview shows the current edit record in the graph. No generated take is auto-approved.
Change shot index and requeue to make the next clip. Model/prompt changes invalidate affected
outputs. The index itself is excluded from renderer signatures to preserve earlier shots.
The graph deliberately processes one video at a time rather than retaining 5–10 minutes of
decoded video in a single mapped graph. The studio scheduler remains available for automatic
long-sequence rendering after capturing its normal renderer templates.

## GPU transitions

The studio uses internal IDGPUStage prompts on ComfyUI's worker queue for reasoning and
cleanup. This prevents an LLM call from overlapping a ComfyUI GPU prompt. Cross-project
studio jobs are serialized. Cleanup uses ComfyUI model unloading, Python collection and
its allocator-cache release. Ollama's selected model is explicitly unloaded and `/api/ps`
is checked before handing the GPU back. Only that model is unloaded; other Ollama clients
and processes are not forcibly stopped. Reserve this pod for the workload for predictable VRAM.

Canvas Director executes directly on the same worker and never waits on a nested queued
prompt. Sheet/shot input nodes and final save nodes release models at stage boundaries.
ComfyUI may retain graph output tensors until its execution cache expires; cleanup does not
claim the entire GPU is empty. Cancelling removes only pending owned prompts. A running
reasoner or render finishes safely; no global interrupt is used.

## Manual GPT-6 Astra API integration

The provider boundary is `infinite_director/providers.py:backend`: a callable receives
`model, system, prompt, images` and returns a Python dict. `response_schema(system)` already
provides the strict object schemas for evidence, bible/designs and shot batches.

For your manual integration, use the Responses API with model `gpt-6-astra`, reasoning
`high`, no tools, `store=False`, a bounded output budget and strict `text.format` JSON schema.
Send text plus the explicitly selected images as `input_image` content. Videos are already
sampled locally; Astra does not accept raw video/audio. Read `OPENAI_API_KEY` server-side
from the pod environment. Never add it to node widgets or workflow JSON. Validate response
status/refusals before parsing; then keep the existing deterministic plan validation.

A provider sketch (variables supplied by the adapter; not an installed provider):

```python
response = client.responses.create(
    model="gpt-6-astra",
    instructions=system,
    input=[{"role": "user", "content": content}],
    reasoning={"effort": "high"},
    tools=[],
    store=False,
    max_output_tokens=16384,
    text={"format": {
        "type": "json_schema", "name": "director_plan", "strict": True,
        "schema": response_schema(system),
    }},
)
if response.status != "completed":
    raise RuntimeError("Director response incomplete")
result = json.loads(response.output_text)  # Handle a refusal/empty output before parsing.
```

`store=False` disables response application-state storage; it is not a promise of zero
retention across all service logs. This API option has not been added to the provider dropdown
or called; authentication and live API setup are left to you as requested.

Sources: [noninteractive Codex](https://learn.chatgpt.com/docs/non-interactive-mode),
[GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra),
[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[data controls](https://developers.openai.com/api/docs/guides/your-data).
