from pathlib import Path
from types import SimpleNamespace

from theroadragetrip.home import load_home, save_home
from theroadragetrip.osm import ParkingSpace
from theroadragetrip.physics import Car
from theroadragetrip.server import SimulationServer


def _bay(x, y):
    return ParkingSpace(points_m=[(x - 2, y - 1), (x + 2, y - 1), (x + 2, y + 1), (x - 2, y + 1)],
                        bbox=(x - 2, y - 1, x + 2, y + 1), source_building_key=(x, y))


def _server(tmp_path: Path):
    taxi_mgr = SimpleNamespace(notification_msg="", notification_timer=0.0, handle_respawn=lambda x, y: None)
    world = SimpleNamespace(ways=[], spatial_grid=None, parking_spaces=[_bay(0, 0), _bay(100, 0)], building_grid=None,
                            waters=[], taxi_stops=[], taxi_mgr=taxi_mgr)
    return SimpleNamespace(car=Car(x=50.0, y=50.0, heading=0.0, speed=0.0), world=world, language="en", _on_foot=False, _home=None,
                           _home_confirm_s=0.0, homes_file=tmp_path / "homes.json", chosen_city="Oulu",
                           _camx=0.0, _camy=0.0, _notify=lambda message, seconds=3.0: setattr(taxi_mgr, "notification_msg", message))


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
