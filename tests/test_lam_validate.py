"""tools/lam_validate.py: the virtual detector across the road at a LAM station."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("lam_validate", Path(__file__).parents[1] / "tools" / "lam_validate.py")
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


def test_crossings_are_counted_once_per_direction_along_the_bearing_and_near_the_road():
    detector = validate.Detector(0.0, 0.0, 90.0)  # direction 1 runs east
    assert detector.crossings([("east", -5.0, 2.0), ("west", 5.0, -2.0), ("far", -5.0, 100.0)]) == []
    assert sorted(detector.crossings([("east", 3.0, 2.0), ("west", -3.0, -2.0), ("far", 5.0, 100.0)])) == ["1", "2"]
    assert detector.crossings([("east", 9.0, 2.0), ("west", -9.0, -2.0)]) == []  # past it: not again
    assert detector.crossings([("new", 4.0, 0.0)]) == []  # first seen: no previous side
