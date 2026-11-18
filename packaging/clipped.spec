# PyInstaller spec for the one-click desktop build (Windows, macOS, Linux).
#
#   1. cd frontend && npm ci && npm run build      (builds clipped/web)
#   2. python scripts/fetch_ffmpeg.py              (puts ffmpeg + ffprobe in packaging/bin)
#   3. pyinstaller packaging/clipped.spec --noconfirm
#
# Output: dist/clipped/  (a folder with the clipped executable)
# ruff: noqa
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
BIN = ROOT / "packaging" / "bin"

datas = [
    (str(ROOT / "clipped" / "assets"), "clipped/assets"),
]
web = ROOT / "clipped" / "web"
if (web / "index.html").exists():
    datas.append((str(web), "clipped/web"))
else:
    print("WARNING: clipped/web is missing - run `npm run build` in frontend/ first")

binaries = []
if BIN.exists():
    for exe in BIN.iterdir():
        if exe.name.startswith(("ffmpeg", "ffprobe")):
            binaries.append((str(exe), "bin"))
if not binaries:
    print("WARNING: no bundled ffmpeg - users will need ffmpeg on PATH (run scripts/fetch_ffmpeg.py)")

hiddenimports = []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("certifi")
hiddenimports += collect_submodules("uvicorn")
hiddenimports += collect_submodules("keyring.backends")
hiddenimports += collect_submodules("yt_dlp.extractor")
hiddenimports += collect_submodules("clipped")
hiddenimports += ["anthropic", "multipart", "python_multipart", "tzdata"]
datas += collect_data_files("tzdata")

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "pytest", "IPython", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
icon = ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns")
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="clipped",
    console=True,  # the console window is how you see it running and how you quit it
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="clipped")
