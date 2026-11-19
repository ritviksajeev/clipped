"""On Windows a windowless app opens a console window for every console
program it starts unless told not to. Every subprocess call must pass
**hidden() (clipped/proc.py)."""

import ast
import subprocess
import sys
from pathlib import Path

from clipped import proc

ROOT = Path(__file__).resolve().parent.parent / "clipped"


def test_every_subprocess_call_hides_its_window():
    missing = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr in {"run", "Popen", "call", "check_call", "check_output"}
                    and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
                continue
            hides = any((k.arg is None and isinstance(k.value, ast.Call) and getattr(k.value.func, "id", "") == "hidden")
                        or k.arg == "creationflags"  # chose its own window flags (e.g. a detached launch)
                        for k in node.keywords)
            if not hides:
                missing.append(f"{path.relative_to(ROOT.parent)}:{node.lineno}")
    assert not missing, "subprocess calls that would flash a console window on Windows: " + ", ".join(missing)


def test_hidden_flags(monkeypatch):
    if sys.platform == "win32":
        kw = proc.hidden()
        assert kw["creationflags"] & subprocess.CREATE_NO_WINDOW
        assert kw["startupinfo"].wShowWindow == 0
    else:
        assert proc.hidden() == {}
