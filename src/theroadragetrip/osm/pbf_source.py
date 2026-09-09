"""Local OSM .pbf extract as an alternative to live Overpass API fetches.

Overpass needs a network round-trip per bbox and is subject to public-
instance rate limits, outages, and plain internet flakiness. When a local
.osm.pbf file is available (e.g. assets/osm/finland-latest.osm.pbf from
Geofabrik), this module answers the exact same bbox queries from it instead -
no downloads, no rate limits, works offline.

Extraction itself is delegated to the `osmium` command-line tool
(osmium-tool - https://osmcode.org/osmium-tool/, apt/brew/conda package
"osmium-tool") rather than hand-rolled: cutting a bbox with fully-resolved
way and multipolygon-relation geometry out of a nationwide file correctly
needs multiple passes over the data and careful handling of dense-node
encoding, relation completeness, etc. - exactly what libosmium already does
and osmium-tool already exposes as `osmium extract --strategy=smart`.
Reimplementing that in Python would be a much bigger, riskier piece of code
for the same result.

The result is converted from OSM XML to the same list-of-element-dicts
shape build_ways() already expects from Overpass's JSON, and shares its
on-disk bbox cache - so this is a drop-in fetch_func, no changes needed
anywhere else in the pipeline.
"""
import logging
import os
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)


DEFAULT_FINLAND_PBF_PATH = Path(__file__).resolve().parent.parent / "assets" / "osm" / "finland-latest.osm.pbf"

# "complete_ways" (osmium's own default) leaves multipolygon relations
# possibly incomplete at the edges (see `osmium help extract`); "smart"
# additionally makes multipolygon relations touching the bbox reference-
# complete, matching Overpass's recursive `>;` fetch of every element a
# match depends on. Both run in comparable wall-clock time in practice
# (I/O and decompression bound, not pass-count bound), so there is no real
# reason to accept the extra risk of an incomplete water body or building
# outline for a marginal speed difference.
EXTRACT_STRATEGY = "smart"


def local_pbf_available(pbf_path: Optional[Path] = None) -> bool:
    """Whether a local .pbf extract source is actually usable here: the
    file exists and the `osmium` CLI (osmium-tool) is on PATH."""
    path = Path(pbf_path) if pbf_path else DEFAULT_FINLAND_PBF_PATH
    return path.is_file() and shutil.which("osmium") is not None


def fetch_osm_ways_from_pbf(
    bbox: Tuple[float, float, float, float],
    pbf_path: Optional[Path] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
    force_refresh: bool = False,
) -> List[dict]:
    """Extract OSM elements for `bbox` from a local .osm.pbf file.

    Signature and return shape match fetch_osm_ways() (Overpass) closely
    enough to be used as a drop-in fetch_func - including sharing its
    on-disk bbox cache, so a re-visited area is a cache hit here too and
    doesn't pay the extraction cost again.
    """
    # Re-read from the package each call so tests can monkeypatch
    # theroadragetrip.osm.load_osm_cache / .save_osm_cache.
    from . import load_osm_cache, save_osm_cache

    south, west, north, east = bbox

    if progress_callback:
        progress_callback(0.1, "Checking cache...")
    force_refresh = force_refresh or os.getenv("OVERPASS_FORCE_REFRESH", "0").lower() in ("1", "true", "yes")
    if not force_refresh:
        cached = load_osm_cache(bbox)
        if cached is not None:
            logger.info("Loaded OSM data from local cache")
            if progress_callback:
                progress_callback(0.5, f"Loaded {len(cached)} cached elements")
            return cached

    path = Path(pbf_path) if pbf_path else DEFAULT_FINLAND_PBF_PATH
    if not path.is_file():
        raise FileNotFoundError(f"Local OSM extract not found: {path}")
    if shutil.which("osmium") is None:
        raise RuntimeError(
            "osm_source=pbf requires the 'osmium' command-line tool "
            "(osmium-tool). Install it with your package manager, e.g. "
            "'apt install osmium-tool', 'brew install osmium-tool', or "
            "'conda install -c conda-forge osmium-tool'."
        )

    if progress_callback:
        progress_callback(0.2, f"Extracting from {path.name}...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = os.path.join(tmp_dir, "extract.osm")
        cmd = [
            "osmium", "extract",
            "--bbox", f"{west},{south},{east},{north}",
            f"--strategy={EXTRACT_STRATEGY}",
            "-f", "osm",
            "-O",
            "-o", out_path,
            str(path),
        ]
        logger.info("Extracting local OSM data: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"osmium extract failed (exit {result.returncode}): {result.stderr.strip()}")

        if progress_callback:
            progress_callback(0.5, "Parsing local extract...")
        elements = _parse_osm_xml(out_path)

    logger.info("Loaded %d elements from local PBF extract (%s)", len(elements), path.name)
    try:
        save_osm_cache(bbox, elements)
    except Exception:
        pass
    if progress_callback:
        progress_callback(0.6, f"Loaded {len(elements)} elements")
    return elements


def _parse_osm_xml(path: str) -> List[dict]:
    """Stream-parse OSM XML into the same element-dict shape Overpass's
    JSON output uses (node: lat/lon/tags; way: nodes/tags; relation:
    members/tags), so build_ways() can't tell the two apart.

    Uses "start"+"end" events (not just "end") so each processed top-level
    element can be detached from the root once done - the plain
    Element.clear() idiom alone only frees the element's own children, not
    its slot in the root's own children list, which would otherwise hold
    the entire (potentially many-MB) parsed tree in memory regardless.
    """
    elements: List[dict] = []
    root = None
    for event, elem in ET.iterparse(path, events=("start", "end")):
        if event == "start":
            if root is None:
                root = elem
            continue
        tag = elem.tag
        if tag == "node":
            elements.append({
                "type": "node",
                "id": int(elem.get("id")),
                "lat": float(elem.get("lat")),
                "lon": float(elem.get("lon")),
                "tags": {t.get("k"): t.get("v") for t in elem.findall("tag")},
            })
        elif tag == "way":
            elements.append({
                "type": "way",
                "id": int(elem.get("id")),
                "nodes": [int(nd.get("ref")) for nd in elem.findall("nd")],
                "tags": {t.get("k"): t.get("v") for t in elem.findall("tag")},
            })
        elif tag == "relation":
            elements.append({
                "type": "relation",
                "id": int(elem.get("id")),
                "members": [
                    {"type": m.get("type"), "ref": int(m.get("ref")), "role": m.get("role") or ""}
                    for m in elem.findall("member")
                ],
                "tags": {t.get("k"): t.get("v") for t in elem.findall("tag")},
            })
        else:
            continue
        elem.clear()
        if root is not None:
            root.remove(elem)
    return elements
