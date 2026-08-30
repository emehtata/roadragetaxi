import math

from theroadragetrip.brawl import TaxiBrawlManager
from theroadragetrip.osm import TaxiStop, Way
from theroadragetrip.physics import Car
from theroadragetrip.traffic import NPCCar, TrafficManager


def road():
    return Way([(0.0, 0.0), (200.0, 0.0)], "residential", 4.5, name="Brawl Street")


def opponent():
    return NPCCar(
        x=14.0,
        y=0.0,
        heading=math.pi,
        speed=0.0,
        way=road(),
        segment_idx=0,
        direction=-1,
        target_speed=0.0,
        color=(245, 205, 35),
        is_taxi=True,
    )


def test_brawl_starts_near_taxi_stop(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    manager = TaxiBrawlManager()

    manager.update(Car(0.0, 0.0, 0.0, 0.0), traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1)

    assert manager.brawl is not None
    assert manager.brawl.state == "challenge"
    assert challenger.blocked_timer > 0.0


def test_brawl_uses_nearest_taxi_stop(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    spawn_position = {}

    def spawn_npc(near_x, near_y, **kwargs):
        spawn_position["x"] = near_x
        spawn_position["y"] = near_y
        traffic.npcs.append(challenger)
        return challenger

    traffic.spawn_npc = spawn_npc
    manager = TaxiBrawlManager()

    manager.update(
        Car(9.0, 0.0, 0.0, 0.0),
        traffic,
        [TaxiStop(0.0, 0.0), TaxiStop(10.0, 0.0)],
        0.0,
        0.1,
    )

    assert spawn_position == {"x": 10.0, "y": 0.0}


def test_brawl_challenger_drives_from_outside_view_to_stop():
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    challenger.x = 100.0
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    manager = TaxiBrawlManager()
    car = Car(0.0, 0.0, 0.0, 0.0)
    viewport = (-20.0, -20.0, 20.0, 20.0)

    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1, viewport_bounds=viewport)

    assert manager.brawl is not None
    assert manager.brawl.state == "approach"
    for _ in range(100):
        manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1, viewport_bounds=viewport)
        if manager.brawl.state == "challenge":
            break

    assert manager.brawl.state == "challenge"
    assert math.hypot(challenger.x, challenger.y) <= 8.0


def test_driving_away_escapes_before_fight(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    manager = TaxiBrawlManager()
    car = Car(0.0, 0.0, 0.0, 0.0)
    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1)

    car.x = 40.0
    car.speed = 5.0
    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1)

    assert manager.brawl is None
    assert challenger not in traffic.npcs


def test_distant_challenger_cannot_start_brawl(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    challenger.x = 100.0
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    manager = TaxiBrawlManager()
    car = Car(0.0, 0.0, 0.0, 0.0)

    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 0.1)
    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 0.0, 3.1)

    assert manager.brawl is None
    assert challenger not in traffic.npcs


def test_full_rage_guarantees_win_after_dust_phase(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    manager = TaxiBrawlManager()
    score_changes = []
    car = Car(0.0, 0.0, 0.0, 0.0)
    update = lambda dt: manager.update(
        car, traffic, [TaxiStop(0.0, 0.0)], 1.0, dt, score_callback=score_changes.append
    )
    update(0.1)
    update(3.0)
    assert manager.brawl is not None
    assert manager.brawl.state == "fight"
    update(5.0)

    assert manager.brawl is not None
    assert manager.brawl.winner == "player"
    assert score_changes == [1000]
    assert manager.brawl.curse_timer > 0.0
    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 1.0, 8.0)
    assert manager.brawl is not None
    assert manager.brawl.state == "drive"
    manager.update(car, traffic, [TaxiStop(0.0, 0.0)], 1.0, 0.1)
    assert manager.brawl is None
    assert challenger not in traffic.npcs


def test_npc_winner_waits_at_taxi_stop(monkeypatch):
    traffic = TrafficManager([road()], target_count=0)
    challenger = opponent()
    traffic.spawn_npc = lambda *args, **kwargs: traffic.npcs.append(challenger) or challenger
    monkeypatch.setattr("theroadragetrip.brawl.random.random", lambda: 1.0)
    manager = TaxiBrawlManager()
    score_changes = []
    car = Car(0.0, 0.0, 0.0, 0.0)
    stops = [TaxiStop(0.0, 0.0)]

    update = lambda dt: manager.update(car, traffic, stops, 0.0, dt, score_callback=score_changes.append)
    update(0.1)
    update(3.0)
    update(5.0)
    update(8.0)
    assert manager.brawl is not None
    assert manager.brawl.state == "drive"
    assert score_changes == [-500]
    manager.update(car, traffic, stops, 0.0, 1.0)
    assert manager.brawl is not None
    assert challenger.x < 14.0
    manager.update(car, traffic, stops, 0.0, 1.0)
    manager.update(car, traffic, stops, 0.0, 0.1)

    assert manager.brawl is None
    assert challenger in traffic.npcs
    assert challenger.waiting_at_taxi_stop is True
    assert (challenger.x, challenger.y) == (0.0, 0.0)
