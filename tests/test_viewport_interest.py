"""Camera reports are bounded and dynamic interest includes physical safety."""
import pytest

from theroadragetrip.viewport import client_view_bounds, simulation_bounds, in_bounds


@pytest.mark.parametrize("value", [None, [], [0, 0, 0, 10], [0, 0, 2001, 10],
                                    [False, 0, 10, 10], [0, 0, float("nan"), 10],
                                    [0, 0, float("inf"), 10], "0,0,10,10"])
def test_bad_camera_reports_are_ignored(value):
    assert client_view_bounds({"command": {"view_bounds": value}}) is None


def test_camera_report_preserves_world_coordinates_and_all_edges():
    assert client_view_bounds({"command": {"view_bounds": [1000, -2000, 1200, -1900]}}) == (1000, -2000, 1200, -1900)
    assert client_view_bounds({}) is None


def test_interest_keeps_panned_view_and_player_and_grows_with_speed():
    view = (500, 500, 700, 600)
    stationary = simulation_bounds(view, 0, 0, 0)
    fast = simulation_bounds(view, 0, 0, 210 / 3.6)
    assert in_bounds(stationary, 0, 0)
    assert in_bounds(stationary, 700, 600)
    assert fast[2] > stationary[2] and fast[3] > stationary[3]
    assert simulation_bounds(view, 0, 0, -210 / 3.6) == fast
    assert in_bounds((0, 0, 10, 10), 11, 5, 2)  # body overlaps the edge
