# PyInstaller spec for the one-click desktop build (Windows, macOS, Linux).
#
#   1. cd frontend && npm ci && npm run build      (builds clipped/web)
#   2. python scripts/fetch_ffmpeg.py              (puts ffmpeg + ffprobe in packaging/bin)
#   3. pyinstaller packaging/clipped.spec --noconfirm
#
# Output: dist/clipped/ with two executables sharing one set of libraries:
#   clipped      the desktop app (no console window; opens clipped in its own window)
#   clipped-cli  the same program with a console, for `clipped-cli doctor`, `process` etc.
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
if sys.platform == "darwin":
    d, b, h = collect_all("webview")  # native window on macOS
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("tzdata")

def analysis(script):
    return Analysis(
        [str(ROOT / "packaging" / script)],
        pathex=[str(ROOT)],
        binaries=binaries,
        datas=datas,
        hiddenimports=hiddenimports,
        excludes=["tkinter", "matplotlib", "pytest", "IPython", "torch", "tensorflow"],
        noarchive=False,
    )


icon = ROOT / "packaging" / ("icon.ico" if sys.platform == "win32" else "icon.icns")
icon = str(icon) if icon.exists() else None

app_a = analysis("app_launcher.py")
cli_a = analysis("launcher.py")
app_exe = EXE(PYZ(app_a.pure), app_a.scripts, [], exclude_binaries=True, name="clipped",
              console=False, icon=icon)  # a desktop app: no console window
cli_exe = EXE(PYZ(cli_a.pure), cli_a.scripts, [], exclude_binaries=True, name="clipped-cli",
              console=True, icon=icon)
coll = COLLECT(app_exe, cli_exe, app_a.binaries, app_a.datas, cli_a.binaries, cli_a.datas, name="clipped")
