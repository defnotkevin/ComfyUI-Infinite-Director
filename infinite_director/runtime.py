from pathlib import Path
import os
from .core import Store
from .engine import Engine, ComfyClient

_instance = None


def runtime():
    global _instance
    if _instance is None:
        import folder_paths
        from comfy.cli_args import args
        root = Path(os.environ.get("INFINITE_DIRECTOR_HOME", str(Path(folder_paths.get_output_directory()) / "infinite_director")))
        store = Store(root)
        port = getattr(args, "port", 8188)
        client = ComfyClient(f"http://127.0.0.1:{port}", folder_paths.get_output_directory(), folder_paths.get_temp_directory())
        _instance = (store, Engine(store, client))
    return _instance
