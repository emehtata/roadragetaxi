import os
import subprocess
import sys
from pathlib import Path

from theroadragetrip.parent_watch import is_alive


def test_a_watched_process_exits_with_its_parent():
    parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    child = subprocess.Popen([sys.executable, "-c",
                              f"import time; from theroadragetrip.parent_watch import exit_with_parent; "
                              f"exit_with_parent({parent.pid}); time.sleep(60)"],
                             env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")})
    try:
        assert is_alive(parent.pid)
        parent.kill()
        parent.wait()
        assert not is_alive(parent.pid)
        assert child.wait(timeout=10) == 0
    finally:
        parent.kill()
        child.kill()
