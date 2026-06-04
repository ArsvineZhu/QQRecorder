import ast
from pathlib import Path


def test_agent_plugin_has_no_cross_plugin_imports():
    plugin_root = Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    forbidden = "plugins." + "qq_" + "grok_" + "reply"
    for path in plugin_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(forbidden):
                    offenders.append(str(path.relative_to(plugin_root)))
                    break
            if isinstance(node, ast.Import):
                if any(alias.name.startswith(forbidden) for alias in node.names):
                    offenders.append(str(path.relative_to(plugin_root)))
                    break

    assert offenders == []
