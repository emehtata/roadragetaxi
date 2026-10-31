from theroadragetrip.physics import Car
from theroadragetrip.osm import AutoFetchManager, Way
from theroadragetrip.osm import _snap_projected_bbox


class FakeTransformer:
    def transform(self, x, y):
        # Very simple fake: identity for lon/lat in small coords (meters -> degrees kinda)
        # This is just to test logic, not accurate projection
        return (x / 1000.0, y / 1000.0)


def test_auto_fetch_bbox_snaps_to_stable_tile_key():
    assert _snap_projected_bbox((2490.0, 10.0, 2990.0, 510.0), 500.0) == (
        2000.0, 0.0, 3000.0, 1000.0
    )
    assert _snap_projected_bbox((2410.0, 20.0, 2910.0, 520.0), 500.0) == (
        2000.0, 0.0, 3000.0, 1000.0
    )


def test_endpoint_fetch_audit_reports_cycleway_as_non_blocking():
    road = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="secondary", half_width_m=6.0)
    cycleway = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="cycleway",
        half_width_m=2.0,
        is_drivable=False,
    )
    car = Car(x=90.0, y=0.0, heading=0.0, speed=0.0)
    manager = AutoFetchManager([road, cycleway], (-1_000.0, -1_000.0, 1_000.0, 1_000.0), FakeTransformer())

    audit = manager.get_endpoint_fetch_audit(car, margin_m=20.0, tile_size_m=500.0, current_way=road)

    assert audit["status"] == "evaluated"
    assert audit["connected_to_drivable_road"] is False
    assert audit["endpoint_distance_m"] == 10.0
    assert audit["heading_alignment"] == 1.0


