from pathlib import Path
from types import SimpleNamespace

from theroadragetrip.home import load_home, save_home
from theroadragetrip.osm import Building, ParkingSpace
from theroadragetrip.physics import Car, SpatialWayGrid
from theroadragetrip.server import SimulationServer


def _bay(x, y):
    return ParkingSpace(points_m=[(x - 2, y - 1), (x + 2, y - 1), (x + 2, y + 1), (x - 2, y + 1)],
                        bbox=(x - 2, y - 1, x + 2, y + 1), source_building_key=(x - 7, y + 5, x + 7, y + 15))


def _server(tmp_path: Path):
    sounds = []
    taxi_mgr = SimpleNamespace(notification_msg="", notification_timer=0.0, handle_respawn=lambda x, y: None)
    buildings = [Building(points_m=[(x - 7, 5), (x + 7, 5), (x + 7, 15), (x - 7, 15)],
                          bbox=(x - 7, 5, x + 7, 15), building_type="detached") for x in (0, 100)]
    world = SimpleNamespace(ways=[], spatial_grid=None, parking_spaces=[_bay(0, 0), _bay(100, 0)], building_grid=SpatialWayGrid(buildings),
                            waters=[], taxi_stops=[], taxi_mgr=taxi_mgr)
    return SimpleNamespace(car=Car(x=50.0, y=50.0, heading=0.0, speed=0.0), world=world, language="en", _on_foot=False, _home=None, _home_building_key=None,
                           _home_confirm_s=0.0, _homes_in_save=False, _prepared_home=None, _home_preparation=None, homes_file=tmp_path / "homes.json", chosen_city="Oulu",
                           _camx=0.0, _camy=0.0, _inside=None,
                           audio=SimpleNamespace(sounds=sounds, play_group=lambda group, volume=1.0, at=None: sounds.append((group, at))),
                           _notify=lambda message, seconds=3.0: setattr(taxi_mgr, "notification_msg", message))


def press(server):
    SimulationServer._home_pressed(server)
    return server.world.taxi_mgr.notification_msg


def test_home_is_chosen_in_a_yard_confirmed_to_move_and_kept_per_city(tmp_path):
    server = _server(tmp_path)
    assert "house yard" in press(server)  # no home, not in a yard
    server.car.x, server.car.y = 0.0, 0.0
    assert press(server).startswith("Home saved")
    assert load_home(server.homes_file, "Oulu")[:2] == (0.0, 0.0)

    server.car.x = 100.0  # another yard: asks first
    assert "again" in press(server) and server._home[:2] == (0.0, 0.0)
    assert press(server).startswith("Home saved") and server._home[:2] == (100.0, 0.0)

    server.car.x, server.car.y, server.car.speed = 500.0, 500.0, 12.0  # anywhere else: home
    assert press(server) == "Home." and (server.car.x, server.car.y, server.car.speed) == (100.0, 0.0, 0.0)

    save_home(server.homes_file, "Kemi", (1.0, 2.0, 0.5))
    assert load_home(server.homes_file, "Oulu")[:2] == (100.0, 0.0) and load_home(server.homes_file, "Kemi") == (1.0, 2.0, 0.5)


def test_save_homes_are_isolated_and_clear_preserves_other_game_data(tmp_path):
    import json
    from theroadragetrip.home import clear_homes
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    first.write_text(json.dumps({"city": "Oulu", "balance_cents": 123}))
    save_home(first, "Oulu", (1, 2, 3), in_save=True)
    save_home(first, "Kemi", (4, 5, 6), in_save=True)
    save_home(second, "Oulu", (7, 8, 9), in_save=True)
    assert load_home(first, "Oulu", in_save=True) == (1, 2, 3)
    assert load_home(second, "Oulu", in_save=True) == (7, 8, 9)
    clear_homes(first, in_save=True)
    assert load_home(first, "Oulu", in_save=True) is None
    assert load_home(first, "Kemi", in_save=True) is None
    assert load_home(second, "Oulu", in_save=True) == (7, 8, 9)
    assert json.loads(first.read_text())["balance_cents"] == 123
    server = _server(tmp_path)
    server.homes_file, server._homes_in_save = second, True
    server._home, server._home_confirm_s = (7, 8, 9), 6.0
    SimulationServer._clear_home(server)
    assert server._home is None and server._home_confirm_s == 0.0
    assert load_home(second, "Oulu", in_save=True) is None


def test_old_slot_does_not_inherit_global_home(tmp_path):
    save_home(tmp_path / "homes.json", "Oulu", (1, 2, 3))
    assert load_home(tmp_path / "slot.json", "Oulu", in_save=True) is None
