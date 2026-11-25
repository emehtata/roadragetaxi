"""docs/specs/terrain-following-bodies.md part 1: the speed-bump shapes the server shares with the client (godot/buildings_3d.gd
BUMP_PROFILES; tests/fixtures/vertical_profiles.json checks the numbers agree)."""
import math
from types import SimpleNamespace

from theroadragetrip.vertical import BUMP_PROFILES, BumpField, bump_profile


def test_profile_shapes():
    """Each kind rises to its height and is back on the road at its length: smooth for a hump, ramped with a flat top for a table."""
    for kind, (height, length, ramp, _) in BUMP_PROFILES.items():
        assert bump_profile(kind, 0.0) == 0.0 and bump_profile(kind, length) == 0.0 and bump_profile(kind, -1.0) == 0.0
        assert abs(max(bump_profile(kind, length * i / 200) for i in range(201)) - height) < 1e-3
    assert bump_profile("table", 2.3) == BUMP_PROFILES["table"][0] and bump_profile("table", 0.6) == 0.05  # flat top, half way up a 1.2 m ramp
    assert abs(bump_profile("hump", 1.85) - 0.10) < 1e-9 and abs(BUMP_PROFILES["hump"][1] - 3.7) < 1e-9


def test_bump_field_matches_profile():
    """The bump lookup: the profile along the road, nothing beside it, a cushion only 1.8 m wide."""
    hump = SimpleNamespace(x=100.0, y=50.0, direction_angle=math.pi / 2, kind="hump", width_m=6.0)
    cushion = SimpleNamespace(x=0.0, y=0.0, direction_angle=0.0, kind="cushion", width_m=6.0)
    field = BumpField([hump, cushion])
    assert abs(field.height(100.0, 50.0) - bump_profile("hump", 1.85)) < 1e-9  # centre: the peak
    assert abs(field.height(102.9, 50.0) - bump_profile("hump", 1.85)) < 1e-9  # across the 6 m road: still on it
    assert field.height(104.0, 50.0) == 0.0 and field.height(100.0, 50.0 + 2.0) == 0.0  # beyond its 3.7 m
    assert field.height(0.0, 0.0) > 0.07 and field.height(0.0, 0.95) == 0.0 and field.height(0.0, 0.85) > 0.0
    assert field.height(500.0, 500.0) == 0.0




def test_a_bridge_bump_is_not_on_the_road_below():
    bridge = SimpleNamespace(x=0.0, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0, layer=1)
    assert BumpField([bridge]).height(0.0, 0.0) == 0.0 and BumpField([bridge]).ahead(-10.0, 0.0, 0.0, 30.0) is None


def test_the_world_field_follows_a_streamed_swap_of_any_bump():
    """world_bump_field is rebuilt whenever world.speed_bumps changes, also a swap in the middle that keeps its length."""
    from theroadragetrip.vertical import world_bump_field
    bumps = [SimpleNamespace(x=100.0 * i, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0) for i in range(5)]
    world = SimpleNamespace(speed_bumps=bumps)
    first = world_bump_field(world)
    assert world_bump_field(world) is first and first.height(200.0, 0.0) > 0.09
    bumps[2] = SimpleNamespace(x=2000.0, y=0.0, direction_angle=0.0, kind="hump", width_m=6.0)
    assert world_bump_field(world) is not first and world_bump_field(world).height(200.0, 0.0) == 0.0
