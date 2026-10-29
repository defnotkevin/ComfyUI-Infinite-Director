# Runpod setup and persistence

Run inside the existing pod, using the Python executable that launches ComfyUI. Copy this
repository into `ComfyUI/custom_nodes/ComfyUI-Infinite-Director` first, then:

```bash
cd /workspace/ComfyUI/custom_nodes/ComfyUI-Infinite-Director
python scripts/setup_runpod.py --comfy-root /workspace/ComfyUI --all
```

Replace `/workspace/ComfyUI` if your template uses a different installation path. The setup
script does not install or replace ComfyUI itself. Use a current version with native Qwen Image
Edit and LTX support. Restart ComfyUI after installing nodes, then hard-refresh the browser.
Choose **Use bundled Qwen + LTX renderers** in the studio. Missing node types are reported by
name; update your ComfyUI / LTX installation if required.

- `--dry-run --all`: print the installation plan without changing files or using the network.
- Default without `--all`: download models only; requires `huggingface_hub` already installed.
- `--all --skip-models`: dependencies and Ollama only; useful when your weights already exist
  under alternate names and you intend to capture customized graphs.
- `--llm-model NAME`: choose another local Ollama **vision-capable** director model.

All eight Qwen/LTX files are downloaded to the exact `models/diffusion_models`,
`models/text_encoders`, `models/vae`, and `models/latent_upscale_models` paths used by the
bundled workflows. The manifest is `models/infinite-director-models.json`. Downloads are
revision-pinned after metadata resolution, resumable through Hugging Face's local staging
cache, and validated before being moved into place. The disk preflight is conservative and
requires space for all outstanding complete files plus 5 GiB, even if partial files exist.
An existing mismatching file is never silently replaced. Move it aside or use your own renderer.

LTX access is gated. Accept the publisher's conditions at
[the model repository](https://huggingface.co/Lightricks/LTX-2.5), then authenticate with
`HF_TOKEN` in the pod environment or `hf auth login`. The script cannot accept terms for you.
No secret is stored in project manifests or sent to the browser.

The setup script installs Ollama from its official Linux installer only if missing. New daemon
launches bind to loopback and use `ComfyUI/models/ollama`; an existing daemon retains its own
storage configuration. Ensure that location is on your persistent volume. After a pod restart,
if Ollama isn't managed by your pod startup service, start it with:

```bash
OLLAMA_HOST=127.0.0.1:11434 OLLAMA_MODELS=/workspace/ComfyUI/models/ollama ollama serve
```

Keep ComfyUI's output directory persistent too: that contains Infinite Director projects,
uploads, contexts, references, takes and exported scenes. A GPU instance's temporary disk is
not a substitute for a persistent volume. The installer provisions software on an existing
pod; it does not create instances or change your billing.

BF16 defaults prioritize compatibility with the bundled graphs, not minimum VRAM. This setup
has not been benchmarked on your GPU. You can use compatible quantized variants by adjusting
and capturing the graphs; the automatic installer does not guess replacements. Optional
faster-whisper transcription is separate (`requirements-transcription.txt` plus local weights).
