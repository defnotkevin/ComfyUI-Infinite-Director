# Third-party notices

Infinite Director's Python code, browser extension, and original documentation are MIT licensed.

The LTX sampling arrangement in `scripts/build_workflows.py` and the generated
`workflows/03-ltx25-audio-video*.json` adapts the audio-to-video topology published by
[Lightricks/ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo/blob/master/example_workflows/2.5/LTX-2.5_A2V_Two_Stage_Distilled.json):
frozen input audio latents, 8-step distilled generation, 2× latent upscale,
and 3-step refinement. The upstream LTX-2 Community License is preserved in
[docs/LTX-LICENSE.txt](docs/LTX-LICENSE.txt) for this adaptation. Retrieved 2026-10-27.
The new graphs remove remote encoding and prompt enhancement and use Director inputs.
Model weights are not redistributed. Their individual licenses and access conditions apply.

ComfyUI is an external dependency. The native node interfaces are used, not copied.
Qwen model weights, optional camera-angle LoRAs, Whisper models, Ollama models, and
FFmpeg are external dependencies with their own licenses. No inference model is bundled.
