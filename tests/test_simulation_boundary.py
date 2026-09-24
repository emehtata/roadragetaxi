"""client-server-01.md Phase 1: the simulation/rendering boundary.

Covers step 13's checklist: `simulation.py` never imports pygame, and the
extracted tick (`advance_simulation`) is genuinely callable with no
display - proven here by driving it through `--headless`, the same path
a future server process would use.
"""

import ast
import os
import subprocess
import sys

import theroadragetrip.simulation as simulation


def test_simulation_module_has_no_pygame_import():
    tree = ast.parse(open(simulation.__file__).read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(alias.name.split(".")[0] == "pygame" for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is None or node.module.split(".")[0] != "pygame"


def test_player_command_defaults_are_inert():
    command = simulation.PlayerCommand()
    assert (command.throttle, command.brake, command.steer_left, command.steer_right) == (0.0, 0.0, 0.0, 0.0)
    assert (command.forward, command.turn, command.sprint) == (0.0, 0.0, False)
    assert command.refuel is False


def test_headless_mode_runs_simulation_ticks_with_no_display():
    # pytest.ini's `pythonpath = src` only applies to this process; the
    # child needs the package's own src/ directory on its path too.
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(simulation.__file__)))
    env = dict(
        os.environ,
        SDL_VIDEODRIVER="dummy",
        PYTHONPATH=os.pathsep.join(filter(None, [src_dir, os.environ.get("PYTHONPATH")])),
    )
    result = subprocess.run(
        [sys.executable, "-m", "theroadragetrip", "--use-sample", "--no-menu", "--headless", "30"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Headless run: 30 ticks" in result.stdout
