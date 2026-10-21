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


def test_slot_names_cannot_leave_the_saves_folder(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        slot_path(tmp_path / "x.ini", "../evil")
