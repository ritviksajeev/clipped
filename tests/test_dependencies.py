"""Every third-party module the app imports must be a declared dependency.

A package that only happens to be installed on the developer's machine works
in tests and then breaks for users (this is how a missing `tzdata` broke
`clipped serve` on Windows).
"""

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# import name -> distribution name, where they differ
IMPORT_TO_DIST = {
    "yt_dlp": "yt-dlp",
    "faster_whisper": "faster-whisper",
    "PIL": "pillow",
    "multipart": "python-multipart",
    "webview": "pywebview",
}
# provided by a declared package's own dependencies
TRANSITIVE = {"starlette": "fastapi", "anyio": "fastapi"}


def declared() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text("utf-8"))
    names = set()
    for dep in data["project"]["dependencies"]:
        names.add(re.split(r"[<>=\[;\s]", dep, maxsplit=1)[0].lower())
    return names


def imported_top_level() -> set[str]:
    mods = set()
    for path in (ROOT / "clipped").rglob("*.py"):
        tree = ast.parse(path.read_text("utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods.add(node.module.split(".")[0])
    return mods


def test_all_third_party_imports_are_declared():
    deps = declared()
    stdlib = set(sys.stdlib_module_names)
    missing = []
    for mod in sorted(imported_top_level()):
        if mod in stdlib or mod == "clipped":
            continue
        dist = TRANSITIVE.get(mod) or IMPORT_TO_DIST.get(mod, mod)
        if dist.lower().replace("_", "-") not in {d.replace("_", "-") for d in deps}:
            missing.append(f"{mod} (expected '{dist}' in pyproject dependencies)")
    assert not missing, "Undeclared dependencies: " + ", ".join(missing)


def test_tzdata_declared_because_zoneinfo_is_used():
    uses_zoneinfo = "zoneinfo" in imported_top_level()
    assert uses_zoneinfo
    assert "tzdata" in declared(), "zoneinfo needs the tzdata package on Windows"
