# Install ffmpeg (only if it's missing)

The desktop downloads include ffmpeg. You only need this page if the dashboard says **ffmpeg is not installed**, or if you run clipped from source.

clipped needs an ffmpeg build with **libass**, which burns in the captions. All the builds below include it.

## Windows

* With winget, in PowerShell: `winget install --id Gyan.FFmpeg -e`
* Or download the "release full" build from <https://www.gyan.dev/ffmpeg/builds/>, unzip it, and add its `bin` folder to your PATH.

## macOS

* With Homebrew: `brew install ffmpeg-full` (the plain `ffmpeg` formula no longer includes libass, which captions need; clipped finds `ffmpeg-full` by itself)

## Linux

* Debian/Ubuntu: `sudo apt install ffmpeg`
* Fedora: `sudo dnf install ffmpeg` (enable RPM Fusion first)
* Arch: `sudo pacman -S ffmpeg`

## Check it

Run `clipped doctor` (or open **Settings → About** in the dashboard). Every line should say `ok`. To use a specific ffmpeg, set the environment variables `CLIPPED_FFMPEG` and `CLIPPED_FFPROBE` to their full paths.
