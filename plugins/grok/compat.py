import importlib
import sys
from pathlib import Path


def ensure_plugin_root_on_path() -> str:
    plugin_root = str(Path(__file__).resolve().parents[1])
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    return plugin_root


def import_sibling_plugin_module(module_name: str):
    ensure_plugin_root_on_path()
    return importlib.import_module(module_name)
