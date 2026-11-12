import pyproj

from theroadragetrip import geo


def test_transformer_built_once_per_crs_pair(monkeypatch):
    real = pyproj.Transformer.from_crs
    calls = []

    def counting(*args, **kwargs):
        calls.append(args)
        return real(*args, **kwargs)

    if hasattr(geo, "get_transformer"):
        geo.get_transformer.cache_clear()
    monkeypatch.setattr(pyproj.Transformer, "from_crs", counting)
    for i in range(1000):
        geo.meters_to_latlon(385000.0 + i, 6672000.0)
    assert len(calls) <= 1
    a = geo.get_transformer("EPSG:3067", "EPSG:4326")
    assert a is geo.get_transformer("EPSG:3067", "EPSG:4326")
    assert a is not geo.get_transformer("EPSG:4326", "EPSG:3067")


def test_meters_to_latlon_unchanged():
    fresh = pyproj.Transformer.from_crs("EPSG:3067", "EPSG:4326", always_xy=True)
    for x, y in [(385000.0, 6672000.0), (384123.4, 6671987.6), (500000.0, 7000000.0)]:
        lon, lat = fresh.transform(x, y)
        assert geo.meters_to_latlon(x, y) == (lat, lon)
