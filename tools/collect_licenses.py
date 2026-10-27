"""Copy the licence files of everything the bundled server ships into a folder.

    python tools/collect_licenses.py OUT_DIR

Run in the environment PyInstaller builds from (windows-release.yml). Writes
OUT_DIR/<package>/<licence files> for the runtime dependencies (requests,
pyproj, shapely and everything they require) and PyInstaller (its bootloader
is in the executable), OUT_DIR/python/LICENSE.txt for the Python runtime, and
OUT_DIR/PACKAGES.txt listing each package, version and declared licence.
It copies what the packages declare; it does not judge their compatibility
(LICENSE_AUDIT.md does that).
"""
from __future__ import annotations

import importlib.metadata as md
import re
import shutil
import sys
from pathlib import Path

RUNTIME = ["requests", "ephem", "pyproj", "shapely"]  # pyproject.toml dependencies (tests/test_license_inventory.py keeps them in step)
BUNDLED_TOOLS = ["pyinstaller"]  # its bootloader is part of RoadRageServer.exe
LICENCE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE|AUTHORS)", re.IGNORECASE)


def _name(requirement: str) -> str:
    return re.split(r"[ ;<>=!~\[(]", requirement, maxsplit=1)[0].lower()


def runtime_closure(roots: list[str]) -> list[md.Distribution]:
    """The installed distributions `roots` need at run time (extras skipped)."""
    seen: dict[str, md.Distribution] = {}
    todo = list(roots)
    while todo:
        name = todo.pop().lower()
        if name in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        seen[name] = dist
        for requirement in dist.requires or []:
            if "extra ==" not in requirement:
                todo.append(_name(requirement))
    return sorted(seen.values(), key=lambda d: d.metadata["Name"].lower())


def declared_licence(dist: md.Distribution) -> str:
    meta = dist.metadata
    text = meta.get("License-Expression") or (meta.get("License") or "").split("\n")[0]
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return text.strip() or ", ".join(classifiers) or "NOT DECLARED"


def collect(out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    tools = [md.distribution(name) for name in BUNDLED_TOOLS]  # not their build-time dependencies
    for dist in runtime_closure(RUNTIME) + tools:
        name = dist.metadata["Name"]
        files = [f for f in dist.files or [] if LICENCE_FILE.search(f.name) and ".dist-info" in str(f)]
        target = out / name
        for file in files:
            source = Path(dist.locate_file(file))
            relative = Path(*file.parts[1:]) if len(file.parts) > 1 else Path(file.name)
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target / relative)
        rows.append(f"{name} {dist.version}: {declared_licence(dist)}" + ("" if files else "  [NO LICENCE FILE SHIPPED]"))
    python_licence = Path(sys.base_prefix) / "LICENSE.txt"
    if python_licence.is_file():
        (out / "python").mkdir(exist_ok=True)
        shutil.copyfile(python_licence, out / "python" / "LICENSE.txt")
        rows.append(f"Python {sys.version.split()[0]}: PSF-2.0 (python/LICENSE.txt)")
    else:
        rows.append(f"Python {sys.version.split()[0]}: PSF-2.0  [LICENSE.txt NOT FOUND at {python_licence}]")
    (out / "PACKAGES.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return rows


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for row in collect(Path(sys.argv[1])):
        print(row)
