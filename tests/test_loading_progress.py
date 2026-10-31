import sys
import types

import pytest

fake_pyproj = types.SimpleNamespace()


class FakeTransformer:
    @staticmethod
    def from_crs(a, b, always_xy=True):
        return FakeTransformer()

    def transform(self, lon, lat):
        return (lon * 1000.0, lat * 1000.0)


fake_pyproj.Transformer = FakeTransformer


@pytest.fixture(autouse=True)
def _fake_pyproj(monkeypatch):
    """The fake pyproj for this module's tests only, restored after each:
    installed at import, it leaked into every later test (cached
    municipality centres projected with it, e.g. a long fare to nowhere)."""
    monkeypatch.setitem(sys.modules, "pyproj", fake_pyproj)


from theroadragetrip.osm import build_ways


def test_build_ways_progress_callback():
    progress_records = []

    def on_progress(frac: float, msg: str):
        progress_records.append((frac, msg))

    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "primary"}},
    ]

    ways, waters, buildings, sceneries, places, bounds = build_ways(elements, progress_callback=on_progress)
    assert len(progress_records) >= 2
    assert progress_records[-1][0] == 1.0


def test_build_ways_reports_expensive_post_processing():
    progress_records = []
    elements = [
        {"type": "node", "id": 1, "lat": 60.0, "lon": 25.0},
        {"type": "node", "id": 2, "lat": 60.001, "lon": 25.001},
        {"type": "node", "id": 3, "lat": 60.001, "lon": 25.0},
        {
            "type": "way",
            "id": 10,
            "nodes": [1, 2, 3, 1],
            "tags": {"landuse": "park"},
        },
        {
            "type": "relation",
            "id": 20,
            "members": [{"type": "way", "ref": 10, "role": "outer"}],
            "tags": {"type": "multipolygon", "natural": "water"},
        },
    ]

    build_ways(elements, progress_callback=lambda fraction, message: progress_records.append((fraction, message)))

    messages = [message for _, message in progress_records]
    assert any("OSM trees" in message for message in messages)
    assert any("multipolygon" in message for message in messages)
    assert all(
        current >= previous
        for (previous, _), (current, _) in zip(progress_records, progress_records[1:])
    )


