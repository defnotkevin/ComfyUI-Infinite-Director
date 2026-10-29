#!/usr/bin/env python3
"""Explicit, resumable installer. Run with ComfyUI's Python on the pod, not on your laptop."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request

MODELS = [
    ('Comfy-Org/Qwen-Image-Edit_ComfyUI', 'split_files/diffusion_models/qwen_image_edit_2511_bf16.safetensors', 'diffusion_models'),
    ('Comfy-Org/Qwen-Image_ComfyUI', 'split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors', 'text_encoders'),
    ('Comfy-Org/Qwen-Image_ComfyUI', 'split_files/vae/qwen_image_vae.safetensors', 'vae'),
    *[('Lightricks/LTX-2.5', folder + '/' + name, folder) for folder, name in [
        ('diffusion_models', 'ltx-2.5-22b-distilled-transformer-bf16.safetensors'),
        ('text_encoders', 'gemma4-12b-with-proj-ltx-2.5-bf16.safetensors'),
        ('vae', 'ltx-2.5-video-vae-bf16.safetensors'),
        ('vae', 'ltx-2.5-audio-vae-bf16.safetensors'),
        ('latent_upscale_models', 'ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors'),
    ]],
]


def run(*args, **kwargs):
    subprocess.run([str(x) for x in args], check=True, **kwargs)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def matches(path, size, etag):
    return path.is_file() and path.stat().st_size == size and (len(etag) != 64 or sha256(path) == etag)


def download_models(root):
    from huggingface_hub import get_hf_file_metadata, hf_hub_download, hf_hub_url
    model_root = root / 'models'
    model_root.mkdir(exist_ok=True)
    stage = model_root / '.infinite-director-downloads'
    resolved = []
    # Preflight ALL gated access before starting any large download.
    for repo, filename, folder in MODELS:
        meta = get_hf_file_metadata(hf_hub_url(repo, filename), token=os.environ.get('HF_TOKEN'))
        if not meta.size or not meta.commit_hash:
            raise RuntimeError(f'Missing download metadata: {filename}')
        target = model_root / folder / Path(filename).name
        etag = (meta.etag or '').strip('"')
        ready = matches(target, meta.size, etag)
        if target.exists() and not ready:
            raise RuntimeError(f'Existing file differs from upstream; move it aside before replacing: {target}')
        resolved.append((repo, filename, target, meta, etag, ready))
        print(('Verified: ' if ready else 'Download: ') + str(target), flush=True)
    required = sum(m.size for _, _, _, m, _, ready in resolved if not ready)
    free = shutil.disk_usage(model_root).free
    # Conservative: retain partial downloads and allow a safety margin.
    if required + 5 * 1024**3 > free:
        raise RuntimeError(f'Need up to {required / 1024**3:.1f} GiB plus 5 GiB free; available {free / 1024**3:.1f} GiB. Models are not quantized.')
    manifest = []
    for repo, filename, target, meta, etag, ready in resolved:
        if not ready:
            downloaded = Path(hf_hub_download(repo, filename, revision=meta.commit_hash,
                              local_dir=stage / repo.replace('/', '--'), token=os.environ.get('HF_TOKEN')))
            if not matches(downloaded, meta.size, etag):
                raise RuntimeError(f'Integrity check failed: {filename}')
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise RuntimeError(f'Existing file differs from upstream; move it aside before replacing: {target}')
            os.replace(downloaded, target)
        manifest.append(dict(repo=repo, filename=filename, revision=meta.commit_hash, size=meta.size, etag=etag, target=str(target)))
    (model_root / 'infinite-director-models.json').write_text(json.dumps(manifest, indent=2))


def dependencies(root):
    # Pin the pod's CUDA packages so installing custom nodes cannot replace its CUDA build.
    pins = []
    for name in ('torch', 'torchvision', 'torchaudio'):
        try:
            pins.append(f'{name}=={importlib.metadata.version(name)}')
        except importlib.metadata.PackageNotFoundError:
            pass
    if not any(p.startswith('torch==') for p in pins):
        raise RuntimeError('Use the Python environment that runs ComfyUI (torch must already be installed).')
    constraints = root / 'infinite-director-constraints.txt'
    constraints.write_text('\n'.join(pins) + '\n')
    run(sys.executable, '-m', 'pip', 'install', '-c', constraints, '-r', Path(__file__).resolve().parents[1] / 'requirements.txt', 'huggingface_hub>=0.30')
    plugin = root / 'custom_nodes' / 'ComfyUI-LTXVideo'
    if not plugin.exists():
        run('git', 'clone', 'https://github.com/Lightricks/ComfyUI-LTXVideo.git', plugin)
    else:
        print(f'Keeping existing LTX nodes: {plugin} (no automatic git reset/update)')
    req = plugin / 'requirements.txt'
    if req.exists():
        run(sys.executable, '-m', 'pip', 'install', '-c', constraints, '-r', req)
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        if sys.platform == 'linux' and os.geteuid() == 0 and shutil.which('apt-get'):
            run('apt-get', 'update'); run('apt-get', 'install', '-y', 'ffmpeg')
        else:
            raise RuntimeError('Install ffmpeg and ffprobe with the pod package manager.')


def ollama(root, model):
    env = dict(os.environ, OLLAMA_HOST='127.0.0.1:11434', OLLAMA_MODELS=str(root / 'models' / 'ollama'))
    if not shutil.which('ollama'):
        if sys.platform != 'linux':
            raise RuntimeError('--all installs Ollama on Linux Runpod hosts only.')
        installer = root / 'install-ollama.sh'
        urllib.request.urlretrieve('https://ollama.com/install.sh', installer)
        run('sh', installer, env=env)
    def healthy():
        try:
            with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2) as response:
                return response.status == 200
        except OSError:
            return False
    if not healthy():
        with (root / 'infinite-director-ollama.log').open('ab') as log:
            subprocess.Popen(['ollama', 'serve'], env=env, stdout=log, stderr=log, start_new_session=True)
        for _ in range(30):
            if healthy():
                break
            time.sleep(1)
        else:
            raise RuntimeError('Ollama did not start; inspect infinite-director-ollama.log')
    else:
        print('Using existing Ollama daemon; its configured model storage location remains in effect.')
    run('ollama', 'pull', model, env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comfy-root', type=Path, default=Path('/workspace/ComfyUI'))
    parser.add_argument('--all', action='store_true', help='Also install node dependencies, ffmpeg and local Ollama director')
    parser.add_argument('--dry-run', action='store_true', help='Print paths without modifying anything or accessing the network')
    parser.add_argument('--skip-models', action='store_true')
    parser.add_argument('--llm-model', default='qwen3.6:27b-q8_0')
    args = parser.parse_args()
    root = args.comfy_root.expanduser().resolve()
    if args.dry_run:
        print(json.dumps(dict(comfy_root=str(root), install_dependencies=args.all, ollama=args.llm_model if args.all else None,
             models=[] if args.skip_models else [dict(repo=r, source=f, destination=str(root/'models'/d/Path(f).name)) for r,f,d in MODELS]), indent=2))
        return
    if not (root / 'main.py').is_file() or not (root / 'custom_nodes').is_dir():
        parser.error('--comfy-root must point to your existing ComfyUI installation')
    if args.all:
        dependencies(root)
    else:
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            raise RuntimeError('Install huggingface_hub in this Python environment, or use --all.')
    if not args.skip_models:
        download_models(root)
    if args.all:
        ollama(root, args.llm_model)
    print('Setup complete. Restart ComfyUI, open Infinite Director, and choose Use bundled Qwen + LTX renderers.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'Setup stopped: {exc}\nFor gated models, accept the publisher terms on Hugging Face and set HF_TOKEN (never paste it into the studio). Re-run the same command to resume.', file=sys.stderr)
        sys.exit(1)
