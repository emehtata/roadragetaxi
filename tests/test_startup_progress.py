import json
from types import SimpleNamespace

import pytest

from theroadragetrip.server.startup_progress import StartupProgress


def test_status_is_atomic_throttled_and_keeps_bounded_stage_history(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("theroadragetrip.server.startup_progress.time.monotonic", lambda: clock[0])
    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "Karttaa luetaan…")
    assert json.loads(path.read_text())["detail"] == "Karttaa luetaan…"
    progress("world", "throttled")
    assert "throttled" not in path.read_text()
    clock[0] = 1.0
    progress("world", "next detail")
    assert json.loads(path.read_text())["elapsed_s"] == 1.0
    for stage in ["tiles", "merging", "indexes", "weather", "lights", "chunks", "ready"]:
        progress(stage)
    status = json.loads(path.read_text())
    assert status["history"] == ["merging", "indexes", "weather", "lights", "chunks", "ready"]
    assert not path.with_name("status.json.tmp").exists()


def test_unwritable_status_is_not_a_startup_failure(tmp_path):
    parent = tmp_path / "not-a-directory"
    parent.write_text("keep")
    StartupProgress(parent / "status.json")("world")
    assert parent.read_text() == "keep"
    StartupProgress()("world")


def test_run_server_reports_constructor_failure_before_socket_exists(tmp_path, monkeypatch):
    from theroadragetrip import server

    def fail(*args, **kwargs):
        raise ValueError("broken map")

    monkeypatch.setattr(server, "SimulationServer", fail)
    path = tmp_path / "status.json"
    with pytest.raises(ValueError, match="broken map"):
        server.run_server(SimpleNamespace(startup_progress=path), None)
    assert json.loads(path.read_text())["detail"] == "ValueError: broken map"
    assert json.loads(path.read_text())["stage"] == "error"
