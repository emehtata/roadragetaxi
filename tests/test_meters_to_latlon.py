import sys
import types


def test_meters_to_latlon():
    # Install a temporary fake `pyproj` for the duration of this test
    prev = sys.modules.get("pyproj")
    fake_pyproj = types.SimpleNamespace()

    class FakeTransformer:
        @staticmethod
        def from_crs(a, b, always_xy=True):
            return FakeTransformer()

        def transform(self, x, y):
            # Convert meters back to lon/lat by dividing by 1000
            return (x / 1000.0, y / 1000.0)

    fake_pyproj.Transformer = FakeTransformer
    sys.modules["pyproj"] = fake_pyproj

    try:
        from theroadragetrip import meters_to_latlon
        lat, lon = meters_to_latlon(25000.0, 60000.0)
        assert abs(lat - 60.0) < 1e-6
        assert abs(lon - 25.0) < 1e-6
    finally:
        # restore previous module state
        if prev is None:
            del sys.modules["pyproj"]
        else:
            sys.modules["pyproj"] = prev
