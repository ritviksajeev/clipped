"""Desktop entry point: double-click to start ClipPilot and open the dashboard.

Runs `clippilot serve` by default. Any command-line arguments are passed
through, so the bundled executable also works as the CLI:

    ClipPilot process https://clips.twitch.tv/...
    ClipPilot doctor
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from clippilot.cli import main as cli_main

    args = sys.argv[1:]
    print("ClipPilot is starting. Keep this window open while it runs; close it to quit.", flush=True)
    return cli_main(args or ["serve"])


if __name__ == "__main__":
    sys.exit(main())
