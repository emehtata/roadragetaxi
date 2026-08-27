"""Compatibility shim

This file is intentionally tiny: it ensures `python3 road_rage_trip.py` keeps
working after the project was refactored into a package under `src/`.

It puts `src/` on sys.path, imports the package implementation and delegates
execution to `theroadragetrip.main.main()`.
"""

import os
import sys

ROOT = os.path.dirname(__file__)
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

# Re-export package symbols for backward compatibility with `from road_rage_trip import ...`
from theroadragetrip.main import *  # noqa: F401,F403

if __name__ == "__main__":
    main()
