"""Entry point of the bundled simulation server (windows-release.yml builds it
with PyInstaller as server/RoadRageServer.exe beside the Godot game; the game
starts it - see godot/paths.gd). Same as `python -m theroadragetrip.server`."""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")  # headless: pygame (sounds, fonts) without a window
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")  # the Godot client plays every sound
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if os.path.isdir(SRC) and SRC not in sys.path:
    sys.path.insert(0, SRC)

from theroadragetrip.server.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
