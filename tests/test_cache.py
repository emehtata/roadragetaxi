import time

from theroadragetrip.osm import (
    clear_osm_cache,
    has_outdated_osm_cache,
    load_local_sample,
    load_osm_cache,
    save_osm_cache,
)


def test_cache_save_and_load(tmp_path, monkeypatch):
    test_bbox = (64.970, 25.370, 64.990, 25.410)
    sample = load_local_sample()
    assert sample is not None, "sample_osm.json missing"

    monkeypatch.setattr("theroadragetrip.osm.CACHE_DIR", str(tmp_path))
    save_osm_cache(test_bbox, sample)
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*pjson"))
    cached = load_osm_cache(test_bbox)
    assert cached is not None, "Cache not loaded"
    assert len(cached) == len(sample)


def test_cache_loads_covering_bbox(tmp_path, monkeypatch):
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    sample = [{"type": "node", "id": 1}]
    save_osm_cache((64.9, 25.3, 65.1, 25.5), sample)

    assert load_osm_cache((64.95, 25.35, 65.0, 25.45)) == sample
    assert load_osm_cache((64.8, 25.35, 65.0, 25.45)) is None


def test_cache_migrates_legacy_pjson_filename(tmp_path, monkeypatch):
    import json
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    bbox = (64.9, 25.3, 65.1, 25.5)
    legacy_path = tmp_path / "bbox_64p9_25p3_65p1_25p5pjson"
    legacy_path.write_text(
        json.dumps({"version": osm.CACHE_VERSION, "fetched_at": time.time(), "elements": []}),
        encoding="utf-8",
    )

    assert load_osm_cache(bbox) == []
    assert not legacy_path.exists()
    assert (tmp_path / "bbox_64p9_25p3_65p1_25p5.json").exists()


def test_cache_is_removed_when_version_changes(tmp_path, monkeypatch):
    import json
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    bbox = (64.9, 25.3, 65.1, 25.5)
    cache_path = tmp_path / "bbox_64p9_25p3_65p1_25p5.json"
    cache_path.write_text(
        json.dumps({"version": "v-old", "fetched_at": time.time(), "elements": []}),
        encoding="utf-8",
    )

    assert load_osm_cache(bbox) is None
    assert not cache_path.exists()


def test_outdated_cache_is_detected_without_removing_it(tmp_path, monkeypatch):
    import json
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    cache_path = tmp_path / "old.json"
    cache_path.write_text(json.dumps({"version": "v-old"}), encoding="utf-8")

    assert has_outdated_osm_cache() is True
    assert cache_path.exists()


def test_cache_reuses_nearly_identical_point(tmp_path, monkeypatch):
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    sample = [{"type": "node", "id": 1}]
    save_osm_cache((64.9588954907, 25.4605952203, 64.9863415011, 25.5120161418), sample)

    assert load_osm_cache(
        (64.9588975146, 25.4606074748, 64.9863435208, 25.5120284128),
        point=(64.97, 25.48),
    ) == sample


def test_cache_loads_when_point_is_inside_tile(tmp_path, monkeypatch, caplog):
    import theroadragetrip.osm as osm
    import logging

    caplog.set_level(logging.INFO)
    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    sample = [{"type": "node", "id": 1}]
    save_osm_cache((65.0, 25.4, 65.1, 25.5), sample)

    assert load_osm_cache((64.9, 25.3, 65.2, 25.6), point=(65.05, 25.45)) == sample
    assert load_osm_cache((64.9, 25.3, 65.2, 25.6), point=(65.2, 25.45)) is None
    assert "CACHE HIT:" in caplog.text
    assert "reason=car point" in caplog.text
    assert str(tmp_path) in caplog.text


def test_force_refresh_skips_cache(monkeypatch):
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm.requests, "post", lambda *args, **kwargs: type(
        "Response", (), {
            "status_code": 200,
            "json": lambda self: {"elements": [{"type": "node", "id": 99}]},
            "raise_for_status": lambda self: None,
        }
    )())
    monkeypatch.setattr(osm, "load_osm_cache", lambda bbox: [{"type": "node", "id": 1}])

    result = osm.fetch_osm_ways((60.0, 25.0, 60.1, 25.1), force_refresh=True)

    assert result == [{"type": "node", "id": 99}]


def test_clear_osm_cache_removes_all_entries(tmp_path, monkeypatch):
    import theroadragetrip.osm as osm

    monkeypatch.setattr(osm, "CACHE_DIR", str(tmp_path))
    (tmp_path / "map.json").write_text("cache", encoding="utf-8")
    (tmp_path / "dead_ends.json").write_text("cache", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "tile.json").write_text("cache", encoding="utf-8")

    assert clear_osm_cache() == 3
    assert list(tmp_path.iterdir()) == []


def test_fetch_query_requests_taxi_stations(monkeypatch):
    import theroadragetrip.osm as osm

    captured = {}

    class Response:
        status_code = 200

        def json(self):
            return {"elements": []}

        def raise_for_status(self):
            return None

    def post(endpoint, **kwargs):
        captured["query"] = kwargs["data"]["data"]
        return Response()

    monkeypatch.setattr(osm.requests, "post", post)
    monkeypatch.setattr(osm, "load_osm_cache", lambda bbox: None)
    monkeypatch.setattr(osm, "save_osm_cache", lambda bbox, elements: None)
    monkeypatch.delenv("OVERPASS_ENDPOINTS", raising=False)

    osm.fetch_osm_ways((60.0, 25.0, 60.1, 25.1), endpoints=["https://example.test/api"], force_refresh=True)

    assert 'node["highway"="taxi_stop"]' in captured["query"]
    assert 'node["amenity"="taxi"]' in captured["query"]


def test_fetch_uses_next_endpoint_after_failure(monkeypatch):
    import requests
    import theroadragetrip.osm as osm

    monkeypatch.delenv("OVERPASS_ENDPOINTS", raising=False)
    calls = []

    class Response:
        status_code = 200

        def json(self):
            return {"elements": [{"type": "node", "id": 2}]}

        def raise_for_status(self):
            return None

    def post(endpoint, **kwargs):
        calls.append(endpoint)
        if endpoint == "https://first.example/api":
            raise requests.exceptions.ConnectionError("first endpoint unavailable")
        return Response()

    monkeypatch.setattr(osm.requests, "post", post)
    monkeypatch.setattr(osm.time, "sleep", lambda _: None)
    monkeypatch.setattr(osm, "load_osm_cache", lambda bbox: None)
    monkeypatch.setattr(osm, "save_osm_cache", lambda bbox, elements: None)

    result = osm.fetch_osm_ways(
        (60.0, 25.0, 60.1, 25.1),
        endpoints=["https://first.example/api", "https://second.example/api"],
        force_refresh=True,
    )

    assert result == [{"type": "node", "id": 2}]
    assert calls == [
        "https://first.example/api",
        "https://first.example/api",
        "https://first.example/api",
        "https://second.example/api",
    ]

