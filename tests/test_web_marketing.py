"""Exercise both website languages with Node's built-in test runner."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is needed for website JavaScript checks")
def test_website_translations_and_downloads():
    root = Path(__file__).resolve().parents[1]
    subprocess.run(["node", "--test", "web/test.cjs"], cwd=root, check=True, capture_output=True, text=True)
