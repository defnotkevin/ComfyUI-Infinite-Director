"""GPU handoffs executed ONLY inside ComfyUI's prompt worker."""
from __future__ import annotations
import gc
import json
import os
import time
import urllib.request

DEFAULT_MODEL = 'qwen3.6:27b-q8_0'


def release_comfy():
    # Model management moves loaded weights off GPU; collect transient tensors too.
    # Do not call this from aiohttp or a scheduler thread while a prompt may be running.
    import comfy.model_management as mm
    mm.unload_all_models()
    gc.collect()
    mm.soft_empty_cache()


def ollama_request(path, payload=None, timeout=120):
    from .intelligence import local_url
    base = local_url(os.environ.get('INFINITE_DIRECTOR_OLLAMA_URL', 'http://127.0.0.1:11434'))
    req = urllib.request.Request(base + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def unload_reasoner(model, timeout=120):
    """Unload only the selected model and acknowledge residency removal before continuing."""
    ollama_request('/api/generate', {'model':model, 'prompt':'', 'stream':False, 'keep_alive':0}, timeout=timeout)
    names = {model, model + ':latest'} if ':' not in model else {model}
    deadline = time.monotonic() + timeout
    while True:
        running = ollama_request('/api/ps', timeout=min(30, timeout)).get('models', [])
        if not any(m.get('name') in names or m.get('model') in names for m in running):
            return
        if time.monotonic() >= deadline:
            raise TimeoutError('Ollama still holds the director model; GPU handoff stopped. Stop other requests to this model and retry.')
        time.sleep(.25)


def execute_control(store, pid, token):
    """Called by IDGPUStage on the queue worker, never recursively queues a prompt."""
    from .intelligence import ollama_direct
    context = json.loads(store.asset(pid, f'contexts/{token}.gpu.json').read_text())
    action = context['action']
    if action not in ('release', 'reason'):
        raise ValueError('Invalid GPU control operation')
    release_comfy()
    if action == 'reason':
        model = context['model']
        try:
            result = ollama_direct(model, context['system'], context['prompt'],
                                   [store.asset(pid, f) for f in context.get('images', [])])
        finally:
            # Also runs on malformed JSON, transport failures, and reasoning truncation.
            try:
                unload_reasoner(model)
            finally:
                release_comfy()
    else:
        result = {'released': True}
    store.asset(pid, f'contexts/{token}.result.json').write_text(json.dumps(result))
    return result
