"""Regression coverage for the client's ShadowVehicle/ShadowPedestrian
(protocol.py) against the actual render/debug code paths that crashed in
production - not just attribute presence, but real calls into the
render functions and manager methods that read them.

History: population_counts() crashed on a missing vehicle_kind (F7
debug panel); a follow-up blanket __getattr__ "fix" then broke
getattr(ped, "layer", 0)-style defensive reads elsewhere (a TypeError
deep inside bridge-occlusion rendering), because returning None from
__getattr__ prevents getattr()'s own default from ever kicking in.
These tests exercise both failure modes directly so neither regresses.
"""

import pygame
import pytest

from theroadragetrip.npc import NPCVehicleManager
from theroadragetrip.osm import Way
from theroadragetrip.render.common import world_to_screen
from theroadragetrip.render.pedestrians import draw_pedestrians, draw_resident_popup, resident_at_screen_position
from theroadragetrip.render.vehicles import draw_npc_cars
from theroadragetrip import protocol


NPC_DATA = {
    "id": 1, "x": 100.0, "y": 100.0, "heading": 0.5, "speed": 8.0, "color": [10, 20, 30],
    "vehicle_type": "car", "is_taxi": False, "is_police": False, "is_on_foot": False,
    "fallen": False, "layer": 0, "lod_level": 0, "turn_signal": "", "turn_signal_elapsed": 0.0,
    "length_m": 4.5, "width_m": 1.9,
}

PED_DATA = {
    "id": 7, "x": 50.0, "y": 50.0, "heading": 1.0, "radius_m": 0.45, "color": [40, 50, 60],
    "state": "walking", "animation_state": "walking", "animation_time": 0.3,
    "curse_timer": 0.0, "curse_text": "@#*!%", "mood": "normal", "is_cyclist": False,
}


def _shadow_vehicle():
    v = protocol.ShadowVehicle(1)
    v.apply(NPC_DATA)
    return v


def _shadow_pedestrian():
    p = protocol.ShadowPedestrian(7)
    p.apply(PED_DATA)
    return p


def _bridge_way():
    """A higher-layer road overlapping the pedestrian's position - this
    is what actually exercises _covered_by_higher_road's `getattr(way,
    "layer", 0) <= layer` comparison against the pedestrian's own layer."""
    return Way(points_m=[(0.0, 40.0), (100.0, 60.0)], highway="primary", half_width_m=4.0, layer=1)


@pytest.fixture(scope="module", autouse=True)
def _pygame_ready():
    pygame.init()
    pygame.display.set_mode((320, 240))
    yield
    pygame.quit()


def test_shadow_vehicle_survives_population_counts():
    manager = NPCVehicleManager.__new__(NPCVehicleManager)
    manager.vehicles = [_shadow_vehicle()]
    counts = manager.population_counts()
    assert counts["total"] == 1
    assert counts["household"] + counts["autonomous"] == 1

    by_type = manager.population_counts_by_type()
    assert by_type == {"car": 1}


def test_shadow_vehicle_length_and_width_reach_the_renderer():
    # Regression for the top-level-vs-.car-nested mismatch: draw_npc_cars
    # reads getattr(npc, "length_m", ...) on the vehicle itself.
    vehicle = _shadow_vehicle()
    assert vehicle.length_m == 4.5
    assert vehicle.width_m == 1.9


def test_draw_npc_cars_does_not_crash_on_a_shadow_vehicle():
    screen = pygame.display.get_surface()
    draw_npc_cars(screen, [_shadow_vehicle()], camx=100.0, camy=100.0, px_per_m=9.0)


def test_draw_pedestrians_does_not_crash_under_a_higher_layer_road():
    # This is the exact reported crash: a pedestrian near a bridge-like
    # higher-layer way used to blow up in _covered_by_higher_road.
    screen = pygame.display.get_surface()
    draw_pedestrians(
        screen, [_shadow_pedestrian()], camx=50.0, camy=50.0,
        ways=[_bridge_way()], show_debug=True,
    )


def test_draw_pedestrians_debug_mode_does_not_crash():
    screen = pygame.display.get_surface()
    draw_pedestrians(
        screen, [_shadow_pedestrian()], camx=50.0, camy=50.0, show_debug=True, residents={},
    )


def test_resident_at_screen_position_and_popup_do_not_crash():
    ped = _shadow_pedestrian()
    residents = {7: object()}
    click_pos = world_to_screen(ped.x, ped.y, 50.0, 50.0)
    found = resident_at_screen_position([ped], residents, click_pos, camx=50.0, camy=50.0)
    assert found == 7

    screen = pygame.display.get_surface()
    font = pygame.font.SysFont(None, 16)
    draw_resident_popup(screen, font, resident=None, residents=residents, pedestrian=ped)


def test_trip_group_direct_access_pattern_does_not_crash():
    # main/__init__.py's resident-selection block does this exact direct
    # (non-getattr) access on every element of `npcs`.
    npcs = [_shadow_vehicle()]
    selected_trip_group_id = 999
    result = next(
        (
            one_npc.trip_group
            for one_npc in npcs
            if one_npc.trip_group is not None and one_npc.trip_group.group_id == selected_trip_group_id
        ),
        None,
    )
    assert result is None


def test_getattr_with_default_is_not_shadowed_by_a_missing_attribute():
    """Guards against reintroducing a blanket __getattr__ that returns a
    fixed value for anything unset: that breaks every
    getattr(obj, name, default) call site that expects the *caller's*
    default, not the class's, whenever a genuinely-unanticipated
    attribute is read."""
    vehicle = _shadow_vehicle()
    with pytest.raises(AttributeError):
        vehicle.some_attribute_nobody_ever_anticipated

    pedestrian = _shadow_pedestrian()
    with pytest.raises(AttributeError):
        pedestrian.some_attribute_nobody_ever_anticipated
