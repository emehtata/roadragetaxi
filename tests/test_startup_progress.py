import json
import sys
from types import SimpleNamespace

import pytest

from theroadragetrip.server.startup_progress import StartupProgress


def test_status_is_atomic_throttled_and_keeps_bounded_stage_history(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("theroadragetrip.server.startup_progress.time.monotonic", lambda: clock[0])
    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "Karttaa luetaan…")
    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "Karttaa luetaan…"
    progress("world", "throttled")
    assert "throttled" not in path.read_text(encoding="utf-8")
    clock[0] = 1.0
    progress("world", "next detail")
    assert json.loads(path.read_text(encoding="utf-8"))["elapsed_s"] == 1.0
    for stage in ["tiles", "merging", "indexes", "weather", "lights", "chunks", "ready"]:
        progress(stage)
    status = json.loads(path.read_text(encoding="utf-8"))
    assert status["history"] == ["merging", "indexes", "weather", "lights", "chunks", "ready"]
    assert not path.with_name("status.json.tmp").exists()


def test_unwritable_status_is_not_a_startup_failure(tmp_path):
    parent = tmp_path / "not-a-directory"
    parent.write_text("keep")
    StartupProgress(parent / "status.json")("world")
    assert parent.read_text(encoding="utf-8") == "keep"
    StartupProgress()("world")


def test_run_server_reports_constructor_failure_before_socket_exists(tmp_path, monkeypatch):
    from theroadragetrip import server

    def fail(*args, **kwargs):
        raise ValueError("broken map")

    monkeypatch.setattr(server, "SimulationServer", fail)
    path = tmp_path / "status.json"
    with pytest.raises(ValueError, match="broken map"):
        server.run_server(SimpleNamespace(startup_progress=path), None)
    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "ValueError: broken map"
    assert json.loads(path.read_text(encoding="utf-8"))["stage"] == "error"


def test_new_detail_is_written_immediately(tmp_path):
    import json
    from theroadragetrip.server.startup_progress import StartupProgress
    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "Preparing building and scenery indexes...")
    progress("world", "Initializing intercity navigation database...")
    import time
    time.sleep(0.5)
    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "Initializing intercity navigation database..."


def test_status_retries_transient_replace_denial(tmp_path, monkeypatch, caplog):
    from pathlib import Path

    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "old")
    replace = Path.replace
    attempts, delays = [], []

    def temporarily_locked(temporary, target):
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError("Windows reader holds status file")
        return replace(temporary, target)

    monkeypatch.setattr(Path, "replace", temporarily_locked)
    monkeypatch.setattr("theroadragetrip.server.startup_progress.time.sleep", delays.append)
    progress("chunks", "latest")

    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "latest"
    assert len(attempts) == 3 and delays == [0.02, 0.02]
    assert "Could not write startup status" not in caplog.text


def test_status_persistent_replace_denial_is_bounded_and_preserves_last_status(tmp_path, monkeypatch, caplog):
    from pathlib import Path

    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "last readable status")
    delays = []

    def locked(*args):
        raise PermissionError("still locked")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("theroadragetrip.server.startup_progress.time.sleep", delays.append)
    progress("chunks", "not published")

    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "last readable status"
    assert delays == [0.02] * 3
    assert "Could not write startup status" in caplog.text


def test_timer_and_startup_writes_do_not_overlap(tmp_path, monkeypatch):
    import threading
    from pathlib import Path

    clock = [0.0]
    monkeypatch.setattr("theroadragetrip.server.startup_progress.time.monotonic", lambda: clock[0])
    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    write = Path.write_text
    entered, release, flushed = threading.Event(), threading.Event(), threading.Event()
    active, overlaps = [], []

    def paused_write(temporary, *args, **kwargs):
        if active:
            overlaps.append(True)
        active.append(True)
        entered.set()
        assert release.wait(2)
        try:
            return write(temporary, *args, **kwargs)
        finally:
            active.pop()

    monkeypatch.setattr(Path, "write_text", paused_write)
    writer = threading.Thread(target=lambda: progress("world", "one writer"))
    timer = threading.Thread(target=lambda: (progress._flush(), flushed.set()))
    writer.start()
    try:
        assert entered.wait(2)
        clock[0] = 1.0
        timer.start()
        assert not flushed.wait(0.05)
    finally:
        release.set()
        writer.join(2)
        if timer.ident is not None:
            timer.join(2)
    assert not overlaps and flushed.is_set()
    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "one writer"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows file sharing semantics")
def test_windows_status_recovers_when_reader_releases_file(tmp_path, monkeypatch, caplog):
    import threading

    path = tmp_path / "status.json"
    progress = StartupProgress(path)
    progress("world", "previous")
    from pathlib import Path
    replace = Path.replace
    denials = []

    def observed_replace(temporary, target):
        try:
            return replace(temporary, target)
        except PermissionError as error:
            denials.append(error.winerror)
            raise

    monkeypatch.setattr(Path, "replace", observed_replace)
    reader = path.open("r", encoding="utf-8")
    release = threading.Timer(0.03, reader.close)
    release.start()
    try:
        progress("chunks", "after reader closed")
    finally:
        reader.close()
        release.join()
    assert denials
    assert json.loads(path.read_text(encoding="utf-8"))["detail"] == "after reader closed"
    assert "Could not write startup status" not in caplog.text
