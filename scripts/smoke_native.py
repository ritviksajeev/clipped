"""Open clipped's real native window and check its window chrome works.

CI runs this on Windows. The checks live in clipped/selftest.py so a release
build can run them too (`clipped-cli selftest-window`).

    python scripts/smoke_native.py
"""

from clipped.selftest import run

if __name__ == "__main__":
    run()
