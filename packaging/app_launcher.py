"""Desktop app entry point (the windowed `clipped` executable).

Double-click: clipped starts in the background and opens in its own window.
Close the window to quit. Arguments are passed through to the CLI.
"""

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()
    from clipped.cli import main as cli_main

    return cli_main(sys.argv[1:] or ["app"])


if __name__ == "__main__":
    sys.exit(main())
