"""Check that every shipped asset and bundled Python package has a licensing entry.

    python tools/check_license_inventory.py

Reads tools/license_inventory.json. Fails (exit 1) when a file the Windows
release ships (src/theroadragetrip/{assets,img,sounds}, sample_osm.json, the
Godot project's files) matches no entry, when a runtime Python package
(collect_licenses.runtime_closure) has no entry, or when an entry lacks a
required field or has an unknown status. It prints the count per status. It
does not judge licence compatibility: that is LICENSE_AUDIT.md's job.
"""
from __future__ import annotations

import fnmatch
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "tools" / "license_inventory.json"
SHIPPED = ["src/theroadragetrip/assets/", "src/theroadragetrip/img/", "src/theroadragetrip/sounds/", "sample_osm.json", "godot/"]
NOT_SHIPPED = ["godot/tests/", "godot/.gitignore", "godot/export_presets.cfg"]
NOT_ASSETS = (".uid", ".import")  # Godot's per-file metadata: travels with the file it describes
FIELDS = ("name", "paths", "purpose", "shipped", "origin", "licence", "evidence", "obligations", "commercial", "status")
STATUSES = {"verified", "conditional", "unresolved", "not_distributable"}


def shipped_files() -> list[str]:
    tracked = subprocess.run(["git", "ls-files", *SHIPPED], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [f for f in tracked if not f.startswith(tuple(NOT_SHIPPED)) and not f.endswith(NOT_ASSETS)]


def matches(path: str, pattern: str) -> bool:
    # "**/" also matches no folder at all (godot/**/*.gd covers godot/main.gd).
    return (fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.replace("**/", ""))
            or (pattern.endswith("/**") and path.startswith(pattern[:-2])))


def problems(inventory: dict, files: list[str], packages: list[str]) -> list[str]:
    found = []
    for entry in inventory["assets"]:
        missing = [field for field in FIELDS if field not in entry]
        if missing:
            found.append(f"entry {entry.get('name', '?')}: missing {', '.join(missing)}")
        if entry.get("status") not in STATUSES:
            found.append(f"entry {entry.get('name', '?')}: unknown status {entry.get('status')!r}")
    for path in files:
        if not any(matches(path, pattern) for entry in inventory["assets"] for pattern in entry["paths"]):
            found.append(f"no licensing entry for shipped file {path}")
    for name, entry in inventory.get("python_packages", {}).items():
        if entry.get("status") not in STATUSES:
            found.append(f"package {name}: unknown status {entry.get('status')!r}")
    for name in packages:
        if name.lower() not in {key.lower() for key in inventory.get("python_packages", {})}:
            found.append(f"no licensing entry for bundled Python package {name}")
    return found


def main() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from collect_licenses import BUNDLED_TOOLS, RUNTIME, runtime_closure

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    packages = [d.metadata["Name"] for d in runtime_closure(RUNTIME)] + BUNDLED_TOOLS
    found = problems(inventory, shipped_files(), packages)
    for problem in found:
        print("PROBLEM:", problem)
    statuses = Counter(entry["status"] for entry in inventory["assets"])
    statuses.update(entry["status"] for section in ("python_packages", "bundled_software", "runtime_services")
                    for entry in inventory.get(section, {}).values())
    print(", ".join(f"{count} {status}" for status, count in sorted(statuses.items())), f"- {len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
