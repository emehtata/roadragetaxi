import sys

from theroadragetrip.career import save_gig_odometer
from theroadragetrip.save_slots import list_slots, read_slot, slot_path
from theroadragetrip.taxi import TaxiPassenger, TaxiState, TaxiTarget


def _server(tmp_path, monkeypatch, slot="test-slot"):
    monkeypatch.setattr("theroadragetrip.server.CONFIG_PATH", tmp_path / "roadragetrip.ini")
    monkeypatch.setattr(sys, "argv", ["prog", "--use-sample", "--no-menu", "--no-historical-weather", "--save-slot", slot])
    from theroadragetrip.server import SimulationServer
    from theroadragetrip.server.cli import parse_server_args
    args, config = parse_server_args()
    return SimulationServer(args, config)


def test_a_saved_gig_continues_mid_fare_with_money_fuel_pose_and_time(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    taxi = server.world.taxi_mgr
    car = server.car
    car.x, car.y, car.heading, car.fuel_l = car.x + 3.0, car.y - 2.0, 1.25, 17.5
    taxi.balance_cents, taxi.total_score, taxi.completed_fares = 12345, 420, 7
    friend = TaxiPassenger(name="Ville", pickup=TaxiTarget(0.0, 0.0, "Asema"), dropoff=TaxiTarget(9.0, 9.0, "Kotikatu 1"))
    rider = TaxiPassenger(name="Aino", pickup=TaxiTarget(0.0, 0.0, "Asema"),
                          dropoff=TaxiTarget(5000.0, 9000.0, "Tampere", municipality="Tampere"), companions=[friend])
    taxi.current_passenger, taxi.state = rider, TaxiState.DRIVING_TO_DROPOFF
    taxi.fare_started_at, taxi.fare_start_odometer_m, taxi.live_fare_cents = server.calendar.current, car.odometer_m - 900.0, 4200
    game_time = server.calendar.current

    server._pending_save = True
    server.tick(1 / 30)
    assert server.save_count == 1

    again = _server(tmp_path, monkeypatch)
    restored = again.world.taxi_mgr
    assert (again.car.x, again.car.y, again.car.heading) == (car.x, car.y, 1.25)
    assert again.car.fuel_l == 17.5 and restored.balance_cents == 12345
    assert restored.total_score == 420 and restored.completed_fares == 7
    assert abs((again.calendar.current - game_time).total_seconds()) < 1.0
    assert restored.state == TaxiState.DRIVING_TO_DROPOFF and restored.live_fare_cents == 4200
    passenger = restored.current_passenger
    assert passenger.name == "Aino" and passenger.dropoff.municipality == "Tampere" and passenger.boarded
    assert [member.name for member in passenger.members] == ["Aino", "Ville"] and passenger.companions[0].boarded


def test_a_completed_fare_keeps_the_slot_and_the_menu_lists_it(tmp_path):
    config = tmp_path / "roadragetrip.ini"
    path = slot_path(config, "a")
    path.parent.mkdir(parents=True)
    path.write_text('{"city": "Oulu", "bbox": "1,2,3,4", "saved_at": 5, "fare": null}')
    save_gig_odometer(path, 100.0, 20.0, 999)
    data = read_slot(path)
    assert data["city"] == "Oulu" and data["balance_cents"] == 999
    assert [row["name"] for row in list_slots(config)] == ["a"]
    save_gig_odometer(slot_path(config, "unsaved"), 5.0, 30.0)  # a new game's car, never saved
    assert [row["name"] for row in list_slots(config)] == ["a"]


def test_slot_names_cannot_leave_the_saves_folder(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        slot_path(tmp_path / "x.ini", "../evil")


def test_the_slot_list_prints_utf8(tmp_path, monkeypatch, capsys):
    import json
    from theroadragetrip.server import __main__ as server_main
    config = tmp_path / "roadragetrip.ini"
    path = slot_path(config, "a")
    path.parent.mkdir(parents=True)
    path.write_text('{"city": "Inari", "place_name": "Anár, Čeavetjávri", "saved_at": 1}', encoding="utf-8")
    monkeypatch.setattr("theroadragetrip.config.CONFIG_PATH", config)
    monkeypatch.setattr(sys, "argv", ["prog", "--list-saves"])
    server_main.main()
    out = capsys.readouterr().out.strip()
    assert json.loads(out)[0]["place_name"] == "Anár, Čeavetjávri" and "Čeavetjávri" in out  # UTF-8, not escaped


def test_a_legacy_code_page_pipe_still_gets_utf8(tmp_path, monkeypatch):
    """A Windows pipe without UTF-8 mode is cp1252: the server switches it to UTF-8."""
    import io
    import json
    from theroadragetrip.server import __main__ as server_main
    config = tmp_path / "roadragetrip.ini"
    path = slot_path(config, "a")
    path.parent.mkdir(parents=True)
    path.write_text('{"city": "Inari", "place_name": "Čeavetjávri", "saved_at": 1}', encoding="utf-8")
    monkeypatch.setattr("theroadragetrip.config.CONFIG_PATH", config)
    monkeypatch.setattr(sys, "argv", ["prog", "--list-saves"])
    pipe = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(pipe, encoding="cp1252"))
    server_main.main()
    sys.stdout.flush()
    assert json.loads(pipe.getvalue().decode("utf-8"))[0]["place_name"] == "Čeavetjávri"


def test_an_accepted_fare_still_on_its_way_to_pickup_survives_a_save(tmp_path, monkeypatch):
    server = _server(tmp_path, monkeypatch)
    taxi, car = server.world.taxi_mgr, server.car
    pickup = TaxiTarget(car.x + 6.0, car.y, "Asema")
    friend = TaxiPassenger(name="Ville", pickup=pickup, dropoff=TaxiTarget(car.x + 900.0, car.y, "Kotikatu 1"),
                           ped_x=car.x + 7.0, ped_y=car.y + 3.0)
    rider = TaxiPassenger(name="Aino", pickup=pickup, dropoff=TaxiTarget(car.x + 900.0, car.y, "Kotikatu 1"),
                          ped_x=car.x + 6.0, ped_y=car.y + 3.0, companions=[friend])
    taxi.current_passenger, taxi.state = rider, TaxiState.WAITING_FOR_PICKUP
    server._pending_save = True
    server.tick(1 / 30)

    again = _server(tmp_path, monkeypatch)
    restored = again.world.taxi_mgr
    waiting = restored.current_passenger
    assert restored.state == TaxiState.WAITING_FOR_PICKUP and waiting.name == "Aino"
    assert (waiting.ped_x, waiting.ped_y) == (car.x + 6.0, car.y + 3.0)
    assert not waiting.boarded and not waiting.companions[0].boarded
    again.car.x, again.car.y, again.car.speed = car.x, car.y, 0.0  # at the pickup
    for _ in range(30 * 20):
        again.tick(1 / 30)
        if restored.state == TaxiState.DRIVING_TO_DROPOFF:
            break
    assert restored.state == TaxiState.DRIVING_TO_DROPOFF and all(member.boarded for member in waiting.members)


def test_restored_oulu_save_near_raahe_has_local_weather_forecast(tmp_path, monkeypatch):
    import json
    from unittest.mock import Mock
    from theroadragetrip.taxi import municipality_points

    config = tmp_path / 'roadragetrip.ini'
    path = slot_path(config, 'test-slot')
    path.parent.mkdir(parents=True)
    raahe = next(p for p in municipality_points() if p[0] == 'Raahe' and p[4] is None)
    path.write_text(json.dumps({'city': 'Oulu', 'saved_at': 1,
                               'car': {'x': raahe[1], 'y': raahe[2], 'heading': 0},
                               'game_time': '2026-10-21T22:00:00'}))
    server = _server(tmp_path, monkeypatch)
    assert server.chosen_city.casefold() == 'oulu' and server.weather_city == 'Raahe'
    connection = Mock()
    server._on_client_connect(connection)
    message = connection.send.call_args_list[0].args[0]
    assert message['weather_city'] == 'Raahe'


def test_home_belongs_to_slot_and_survives_save_reload_and_clear(tmp_path, monkeypatch):
    from theroadragetrip.home import load_home, save_home
    server = _server(tmp_path, monkeypatch, slot="one")
    city = str(server.chosen_city or "")
    home = (server.car.x, server.car.y, server.car.heading)
    save_home(server.homes_file, city, home, in_save=server._homes_in_save)
    server._home = home
    assert server.save_game()
    assert _server(tmp_path, monkeypatch, slot="one")._home == home
    other = _server(tmp_path, monkeypatch, slot="two")
    assert other._home is None
    server._clear_home()
    assert server.save_game()
    assert _server(tmp_path, monkeypatch, slot="one")._home is None
    assert load_home(server.homes_file, city, in_save=True) is None
    assert read_slot(server.homes_file)["city"] == server.chosen_city
