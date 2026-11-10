"""F2: godot/tests/manifest.txt is the one list of Godot test scripts, run by
tools/run_godot_tests.py for both `make godot-test` and CI."""
import importlib.util
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _runner():
    spec = importlib.util.spec_from_file_location("run_godot_tests", ROOT / "tools" / "run_godot_tests.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_godot_test_is_listed():
    included, excluded = _runner().read_manifest(ROOT / "godot" / "tests" / "manifest.txt")
    assert included, "the manifest runs no tests"
    assert not set(included) & set(excluded), "listed as both included and excluded"
    assert all(reason for reason in excluded.values()), "every excluded script needs a reason"
    listed = set(included) | set(excluded)
    scripts = {f"res://tests/{path.name}" for path in (ROOT / "godot" / "tests").glob("*.gd")}
    assert not scripts - listed, f"not in godot/tests/manifest.txt: {sorted(scripts - listed)}"
    missing = [res for res in listed if not (ROOT / "godot" / res.removeprefix("res://")).is_file()]
    assert not missing, f"manifest lists missing scripts: {missing}"


def test_no_hand_listed_scripts():
    makefile = (ROOT / "Makefile").read_text()
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    for text in (makefile, workflow):
        assert "tools/run_godot_tests.py" in text
        assert "--script res://" not in text


def test_runner_fails_on_quit_1_and_timeout(tmp_path):
    fake = tmp_path / "godot"
    fake.write_text("#!/bin/sh\ncase \"$*\" in\n  *fails.gd*) exit 1;;\n  *hangs.gd*) sleep 30;;\nesac\necho ok\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    manifest = tmp_path / "manifest.txt"
    runner = _runner()
    manifest.write_text("res://tests/passes.gd\n")
    assert runner.main(["--godot", str(fake), "--manifest", str(manifest)]) == 0
    manifest.write_text("res://tests/passes.gd\nres://tests/fails.gd\n")
    assert runner.main(["--godot", str(fake), "--manifest", str(manifest)]) == 1
    manifest.write_text("res://tests/hangs.gd\n[excluded]\nres://tests/x.gd  # a reason\n")
    assert runner.main(["--godot", str(fake), "--manifest", str(manifest), "--timeout", "1"]) == 1
