from theroadragetrip.osm import clear_osm_cache, load_local_sample, load_osm_cache, save_osm_cache


def test_cache_save_and_load(tmp_path, monkeypatch):
    test_bbox = (64.970, 25.370, 64.990, 25.410)
    sample = load_local_sample()
    assert sample is not None, "sample_osm.json missing"

    monkeypatch.setattr("theroadragetrip.osm.CACHE_DIR", str(tmp_path))
    save_osm_cache(test_bbox, sample)
    cached = load_osm_cache(test_bbox)
    assert cached is not None, "Cache not loaded"
    assert len(cached) == len(sample)


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

