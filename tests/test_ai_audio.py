"""CLI validation must work without loading a model or touching the GPU."""
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'ai_audio.py'


@pytest.mark.parametrize('arguments', [[], [''], ['sound','--seconds','nan'],
    ['sound','--seconds','48'], ['sound','--seed','-1']])
def test_invalid_audio_request_fails_before_loading_model(arguments):
    result = subprocess.run([sys.executable,str(SCRIPT),*arguments],capture_output=True,text=True)
    assert result.returncode == 2 and 'error:' in result.stderr
    assert 'torch' not in result.stderr


def test_audio_help_needs_no_gpu():
    result = subprocess.run([sys.executable,str(SCRIPT),'--help'],capture_output=True,text=True)
    assert result.returncode == 0 and '--seconds' in result.stdout and '--seed' in result.stdout
