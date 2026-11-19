"""Console entry point (the `clipped-cli` executable).

With no arguments it opens the app window and shows the log here; otherwise it
is the full CLI:

    clipped-cli doctor
    clipped-cli process https://clips.twitch.tv/...
    clipped-cli serve          (dashboard in your browser instead of a window)
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from clipped.cli import main as cli_main

    args = sys.argv[1:]
    if not args:
        print("clipped is starting. Close the clipped window to quit.", flush=True)
    return cli_main(args or ["app"])


if __name__ == "__main__":
    sys.exit(main())
