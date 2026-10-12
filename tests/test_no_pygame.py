"""0.17.0alpha: the game is the Godot client and this Python simulation;
nothing the server loads may import pygame (it isn't even a dependency)."""
import os
import subprocess
import sys


def test_the_server_and_simulation_never_import_pygame():
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
    code = (
        "import sys; sys.modules['pygame'] = None\n"  # importing it would fail outright
        "import theroadragetrip.server.__main__, theroadragetrip.server.map_sync, theroadragetrip.simulation\n"
        "import theroadragetrip.protocol, theroadragetrip.map_chunks, theroadragetrip.world_loader\n"
        "bad = sorted(m for m in sys.modules if m.startswith(('theroadragetrip.render', 'theroadragetrip.main'))"
        " or m == 'theroadragetrip.audio')\n"
        "assert not bad, bad\n"
    )
    env = dict(os.environ, PYTHONPATH=src)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, env=env)
    assert result.returncode == 0, result.stderr
