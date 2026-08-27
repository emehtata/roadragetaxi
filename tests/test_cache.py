import glob
import json
import os

from theroadragetrip.osm import fetch_osm_ways, load_local_sample, load_osm_cache, save_osm_cache


def test_cache_save_and_load():
    test_bbox = (64.970, 25.370, 64.990, 25.410)
    sample = load_local_sample()
    assert sample is not None, "sample_osm.json missing"

    os.makedirs("osm_cache", exist_ok=True)
    try:
        save_osm_cache(test_bbox, sample)
        cached = load_osm_cache(test_bbox)
        assert cached is not None, "Cache not loaded"
        assert len(cached) == len(sample)
    finally:
        for f in glob.glob(os.path.join("osm_cache", "bbox_64p97_*.json")):
            try:
                os.remove(f)
            except Exception:
                pass

