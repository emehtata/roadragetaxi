"""Tests for the ambient pedestrian activity plugin system (residents-live.md)."""
import math
import pytest

from theroadragetrip.activities import (
    ActivityContext,
    ActivityDefinition,
    ActivityLocation,
    ActivityManager,
    ActivityPlugin,
    ActivityRegistry,
)
from theroadragetrip.activities.plugins import discover
from theroadragetrip.activities.plugins.bench_sitting import BenchSittingPlugin
from theroadragetrip.activities.plugins.garbage_disposal import CARRYING_DISPOSABLE_PROBABILITY, GarbageDisposalPlugin
from theroadragetrip.activities.plugins.park_leisure import ParkLeisurePlugin
from theroadragetrip.activities.plugins.phone_usage import PhoneUsagePlugin
from theroadragetrip.osm import Scenery, SceneryObject, Way
from theroadragetrip.pedestrian import Pedestrian, PedestrianManager
from theroadragetrip.residents import ResidentManager


def _stub_plugin(plugin_id: str) -> ActivityPlugin:
    plugin = ActivityPlugin()
    plugin.definition = ActivityDefinition(id=plugin_id, name=plugin_id)
    return plugin


def _make_manager_and_pedestrian(scenery_objects=None, sceneries=None):
    way = Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="footway", half_width_m=1.5)
    manager = PedestrianManager(
        [way], target_count=0, residents=ResidentManager(),
        scenery_objects=scenery_objects, sceneries=sceneries,
    )
    pedestrian = Pedestrian(10.0, 0.0, 0.0, 1.3, 1.3, way, 0, 1, (1, 1, 1))
    pedestrian.resident_id = manager.residents.create("walking").resident_id
    manager.pedestrians.append(pedestrian)
    return manager, pedestrian


def _context(manager, pedestrian, sim_time=0.0):
    return ActivityContext(pedestrian=pedestrian, pedestrian_manager=manager, residents=manager.residents, sim_time=sim_time)


def test_registry_rejects_duplicate_ids():
    registry = ActivityRegistry()
    registry.register(_stub_plugin("dup"))
    with pytest.raises(ValueError):
        registry.register(_stub_plugin("dup"))


def test_discover_registers_all_four_built_in_plugins():
    registry = ActivityRegistry()
    discover(registry)
    assert {plugin.definition.id for plugin in registry.all_plugins()} == {
        "bench_sitting", "garbage_disposal", "phone_usage", "park_leisure",
    }


def test_discover_skips_a_broken_plugin_module_and_keeps_the_rest(monkeypatch):
    import theroadragetrip.activities.plugins as plugins_pkg

    real_import_module = plugins_pkg.importlib.import_module

    def flaky_import(name, *args, **kwargs):
        if name.endswith("bench_sitting"):
            raise RuntimeError("simulated broken plugin")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(plugins_pkg.importlib, "import_module", flaky_import)
    registry = ActivityRegistry()
    discover(registry)  # must not raise

    ids = {plugin.definition.id for plugin in registry.all_plugins()}
    assert "bench_sitting" not in ids
    assert {"garbage_disposal", "phone_usage", "park_leisure"} <= ids


def test_bench_sitting_finds_a_nearby_bench():
    bench = SceneryObject(x=15.0, y=0.0, kind="bench", direction_angle=1.2)
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[bench])
    plugin = BenchSittingPlugin()

    location = plugin.find_location(_context(manager, pedestrian))

    assert location is not None
    assert (location.x, location.y) == (15.0, 0.0)
    assert location.reservation_key == ("bench", id(bench))


def test_bench_sitting_returns_none_when_no_bench_nearby():
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[])
    plugin = BenchSittingPlugin()

    assert plugin.find_location(_context(manager, pedestrian)) is None


def test_garbage_disposal_can_start_gated_by_carrying_roll(monkeypatch):
    manager, pedestrian = _make_manager_and_pedestrian()
    plugin = GarbageDisposalPlugin()
    context = _context(manager, pedestrian)

    monkeypatch.setattr("theroadragetrip.activities.plugins.garbage_disposal.random.random", lambda: 0.0)
    assert plugin.can_start(context) is True

    monkeypatch.setattr(
        "theroadragetrip.activities.plugins.garbage_disposal.random.random",
        lambda: CARRYING_DISPOSABLE_PROBABILITY,
    )
    assert plugin.can_start(context) is False


def test_garbage_disposal_picks_the_nearest_waste_basket():
    near = SceneryObject(x=12.0, y=0.0, kind="waste_basket")
    far = SceneryObject(x=40.0, y=0.0, kind="waste_basket")
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[far, near])
    plugin = GarbageDisposalPlugin()

    location = plugin.find_location(_context(manager, pedestrian))

    assert location.extra is near


def test_phone_usage_requires_no_location():
    plugin = PhoneUsagePlugin()
    manager, pedestrian = _make_manager_and_pedestrian()

    assert plugin.definition.requires_location is False
    assert plugin.find_location(_context(manager, pedestrian)) is None
    assert plugin.can_start(_context(manager, pedestrian)) is True


def test_park_leisure_interior_point_is_inside_the_polygon_not_just_the_bbox(monkeypatch):
    # An L-shaped (non-convex) park: its bbox includes the notch at (5,5)-(10,10).
    park = Scenery(
        points_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 5.0), (5.0, 5.0), (5.0, 10.0), (0.0, 10.0)],
        kind="park",
        bbox=(0.0, 0.0, 10.0, 10.0),
    )
    manager, pedestrian = _make_manager_and_pedestrian(sceneries=[park])
    pedestrian.x, pedestrian.y = 1.0, 1.0
    plugin = ParkLeisurePlugin()

    # First candidate (7,7) lands in the excluded notch; second (1,1) is inside.
    coordinates = iter([7.0, 7.0, 1.0, 1.0])
    monkeypatch.setattr(
        "theroadragetrip.activities.plugins.park_leisure.random.uniform",
        lambda lo, hi: next(coordinates),
    )
    monkeypatch.setattr(
        "theroadragetrip.activities.plugins.park_leisure.random.choice", lambda seq: seq[0]
    )

    location = plugin.find_location(_context(manager, pedestrian))

    assert location is not None
    assert (location.x, location.y) == (1.0, 1.0)


def test_park_leisure_ignores_non_park_kinds():
    lot = Scenery(points_m=[(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], kind="parking", bbox=(0.0, 0.0, 10.0, 10.0))
    manager, pedestrian = _make_manager_and_pedestrian(sceneries=[lot])
    plugin = ParkLeisurePlugin()

    assert plugin.find_location(_context(manager, pedestrian)) is None


def test_full_bench_sitting_lifecycle_walk_sit_standup_resume():
    bench = SceneryObject(x=30.0, y=0.0, kind="bench")
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[bench])
    plugin = manager.activity_manager.registry.get("bench_sitting")
    location = plugin.find_location(_context(manager, pedestrian))
    assert location is not None

    from theroadragetrip.activities import ActivityInstance

    pedestrian.activity = ActivityInstance(plugin_id=plugin.definition.id, location=location, started_sim_time=0.0)
    pedestrian.state = "walking_to_activity"

    seen_states = set()
    for _ in range(2000):
        manager.sim_time += 0.1
        manager._update_activity(pedestrian, 0.1)
        seen_states.add(pedestrian.state)
        if pedestrian.activity is None:
            break

    assert "walking_to_activity" in seen_states
    assert "performing_activity" in seen_states
    assert pedestrian.activity is None
    assert pedestrian.state == "walking"
    assert manager.activity_manager._reservations == {}


def test_activity_reservation_prevents_double_booking_the_same_bench():
    # A registry with only bench_sitting - isolates the reservation check
    # from ActivityManager's weighted random pick among other plugins.
    registry = ActivityRegistry()
    registry.register(BenchSittingPlugin())
    bench = SceneryObject(x=15.0, y=0.0, kind="bench")
    manager, pedestrian_a = _make_manager_and_pedestrian(scenery_objects=[bench])
    manager.activity_manager = ActivityManager(registry=registry)
    pedestrian_b = Pedestrian(10.0, 5.0, 0.0, 1.3, 1.3, pedestrian_a.way, 0, 1, (1, 1, 1))
    manager.pedestrians.append(pedestrian_b)

    first = manager.activity_manager.select_activity(_context(manager, pedestrian_a))
    assert first is not None and first[0].definition.id == "bench_sitting"

    second = manager.activity_manager.select_activity(_context(manager, pedestrian_b))
    assert second is None


def test_activity_cooldown_prevents_immediate_retrigger():
    manager, pedestrian = _make_manager_and_pedestrian()
    plugin = PhoneUsagePlugin()

    pedestrian.activity_flags["last_activity_id"] = plugin.definition.id
    pedestrian.activity_flags["last_activity_end_time"] = 0.0

    eligible = manager.activity_manager._eligible_for(plugin, _context(manager, pedestrian, sim_time=1.0))
    assert eligible is False

    eligible_later = manager.activity_manager._eligible_for(
        plugin, _context(manager, pedestrian, sim_time=plugin.definition.cooldown_s + 1.0)
    )
    assert eligible_later is True


def test_activity_pedestrians_survive_population_culling_far_from_player():
    from theroadragetrip.physics import Car

    bench = SceneryObject(x=15.0, y=0.0, kind="bench")
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[bench])
    from theroadragetrip.activities import ActivityInstance

    pedestrian.activity = ActivityInstance(plugin_id="bench_sitting", location=None, started_sim_time=0.0)
    pedestrian.state = "walking_to_activity"

    far_away_player = Car(x=5000.0, y=5000.0, heading=0.0, speed=0.0)
    counts = []
    for _ in range(60):
        manager.update(far_away_player, dt=0.2)
        counts.append(len(manager.pedestrians))

    assert all(count == 1 for count in counts[3:]), f"pedestrian count fluctuated: {counts}"


def test_resident_popup_shows_the_ongoing_activity():
    """Clicking a resident mid-activity must surface what they're doing -
    duck-typed off pedestrian.activity, not a registry lookup (see
    render/pedestrians.py's draw_resident_popup)."""
    import pygame

    from theroadragetrip.activities import ActivityInstance
    from theroadragetrip.render.pedestrians import draw_resident_popup

    pygame.init()
    pygame.display.set_mode((400, 300))
    font = pygame.font.SysFont(None, 16)
    manager, pedestrian = _make_manager_and_pedestrian()
    resident = manager.residents.get(pedestrian.resident_id)

    screen_w, screen_h = 800, 600
    without_activity = pygame.Surface((screen_w, screen_h))
    without_activity.fill((0, 0, 0))
    draw_resident_popup(without_activity, font, resident, manager.residents.residents, screen_w=screen_w, screen_h=screen_h)

    pedestrian.activity = ActivityInstance(
        plugin_id="bench_sitting", location=None, started_sim_time=0.0,
        data={"duration_s": 30.0, "elapsed_s": 12.0},
    )
    with_activity = pygame.Surface((screen_w, screen_h))
    with_activity.fill((0, 0, 0))
    draw_resident_popup(with_activity, font, resident, manager.residents.residents, pedestrian=pedestrian, screen_w=screen_w, screen_h=screen_h)

    assert pygame.image.tostring(with_activity, "RGB") != pygame.image.tostring(without_activity, "RGB")


def test_set_target_count_releases_activity_reservation_when_trimming():
    bench = SceneryObject(x=15.0, y=0.0, kind="bench")
    manager, pedestrian = _make_manager_and_pedestrian(scenery_objects=[bench])
    from theroadragetrip.activities import ActivityInstance, ActivityLocation

    location = ActivityLocation(x=15.0, y=0.0, reservation_key=("bench", id(bench)))
    manager.activity_manager._reservations[location.reservation_key] = id(pedestrian)
    pedestrian.activity = ActivityInstance(plugin_id="bench_sitting", location=location, started_sim_time=0.0)

    manager.set_target_count(0)

    assert location.reservation_key not in manager.activity_manager._reservations
