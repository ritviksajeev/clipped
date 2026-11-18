"""Desktop entry point: double-click to start clipped and open the dashboard.

Runs `clipped serve` by default. Any command-line arguments are passed
through, so the bundled executable also works as the CLI:

    clipped process https://clips.twitch.tv/...
    clipped doctor
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from clipped.cli import main as cli_main

    args = sys.argv[1:]
    print("clipped is starting. Keep this window open while it runs; close it to quit.", flush=True)
    return cli_main(args or ["serve"])


if __name__ == "__main__":
    sys.exit(main())
