"""Run the headless Godot assertion scripts listed in godot/tests/manifest.txt.

    python tools/run_godot_tests.py [--godot PATH] [--manifest PATH] [--timeout S]

The one list used by `make godot-test` and CI. Each included script runs as
`godot --headless --path godot --script res://...` with its output streamed;
a non-zero exit (quit(1)) or a timeout fails the run. Exits 0 only if all pass.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GODOT = os.path.expanduser("~/tools/godot/Godot_v4.7.2-stable_linux.x86_64")


def read_manifest(path):
    """(included res:// paths in order, {excluded res:// path: reason}).
    Lines after "[excluded]" are "res://path  # reason"; "#" starts a comment."""
    included, excluded, section = [], {}, "included"
    for raw in Path(path).read_text().splitlines():
        script, _, comment = raw.partition("#")
        script = script.strip()
        if script == "[excluded]":
            section = "excluded"
        elif script and section == "excluded":
            excluded[script] = comment.strip()
        elif script:
            included.append(script)
    return included, excluded


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--godot", default=os.environ.get("GODOT", DEFAULT_GODOT))
    parser.add_argument("--manifest", default=str(ROOT / "godot" / "tests" / "manifest.txt"))
    parser.add_argument("--timeout", type=float, default=600.0, help="seconds per script")
    args = parser.parse_args(argv)
    included, _ = read_manifest(args.manifest)
    results = []
    for script in included:
        print(f"=== {script}", flush=True)
        started = time.monotonic()
        try:
            code = subprocess.run([args.godot, "--headless", "--path", str(ROOT / "godot"), "--script", script],
                                  timeout=args.timeout).returncode
            status = "PASS" if code == 0 else f"FAIL (exit {code})"
        except subprocess.TimeoutExpired:
            status = f"FAIL (timeout {args.timeout:g} s)"
        results.append((script, status, time.monotonic() - started))
    print("\n=== Godot test summary", flush=True)
    for script, status, seconds in results:
        print(f"{status:<20} {seconds:6.1f} s  {script}")
    failed = sum(1 for _, status, _ in results if status != "PASS")
    print(f"{len(results) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
