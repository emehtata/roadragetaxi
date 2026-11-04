"""A Windows client's WSL path maps to the Linux path the server writes to."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from theroadragetrip.server import server_path


@pytest.mark.skipif(os.sep != "/", reason="the mapping is for a Linux server")
def test_wsl_unc_paths_become_linux_paths():
    assert server_path(r"\\wsl.localhost\Ubuntu-24.04\home\ubuntu\x\server_debug.json") == "/home/ubuntu/x/server_debug.json"
    assert server_path(r"\\wsl$\Ubuntu-24.04\home\ubuntu\x.json") == "/home/ubuntu/x.json"


def test_other_paths_are_unchanged():
    assert server_path("/home/ubuntu/x.json") == "/home/ubuntu/x.json"
    assert server_path(r"C:\Users\me\x.json") == r"C:\Users\me\x.json"
