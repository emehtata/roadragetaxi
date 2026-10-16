import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

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


def test_windows_process_wait_results(monkeypatch):
    import ctypes

    from theroadragetrip import parent_watch

    result = 0
    kernel32 = SimpleNamespace(
        OpenProcess=lambda *_: 1,
        WaitForSingleObject=lambda *_: result,
        CloseHandle=lambda *_: None,
    )
    monkeypatch.setattr(parent_watch.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)

    assert parent_watch.is_alive(123) is False
    result = 258
    assert parent_watch.is_alive(123) is True
    result = 42
    with pytest.raises(OSError, match="Unexpected WaitForSingleObject result"):
        parent_watch.is_alive(123)
