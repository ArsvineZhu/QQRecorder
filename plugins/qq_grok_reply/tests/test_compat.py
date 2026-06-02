import importlib
import sys

from plugins.qq_grok_reply.compat import ensure_plugin_root_on_path


def test_ensure_plugin_root_on_path_enables_sibling_plugin_imports():
    plugin_root = ensure_plugin_root_on_path()
    sys.path = [entry for entry in sys.path if entry != plugin_root]

    plugin_root = ensure_plugin_root_on_path()
    module = importlib.import_module("qq_recorder.text_utils")

    assert plugin_root in sys.path
    assert hasattr(module, "unescape_text")
