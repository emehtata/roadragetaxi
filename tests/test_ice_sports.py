from theroadragetrip.osm import Scenery, Way
from theroadragetrip.pedestrian import PedestrianManager
from theroadragetrip.physics import Car
from theroadragetrip.taxi import TaxiManager

RINK = [(0.0, 10.0), (40.0, 10.0), (40.0, 30.0), (0.0, 30.0)]


def _manager(kind="ice_rink"):
    sidewalk = Way(points_m=[(-10.0, 5.0), (60.0, 5.0)], highway="footway", half_width_m=2.0)
    manager = PedestrianManager([sidewalk], target_count=0)
    manager.set_scenery_features([], [Scenery(RINK, kind, bbox=(0.0, 10.0, 40.0, 30.0))])
    return manager


def _inside(ped):
    return 0.0 <= ped.x <= 40.0 and 10.0 <= ped.y <= 30.0


def test_open_ice_gets_hockey_players_who_stay_on_it_and_leave_when_it_closes():
    manager = _manager()
    car = Car(x=20.0, y=0.0, heading=0.0, speed=0.0)
    manager.ensure_ice_skaters(car)
    assert not manager.pedestrians  # the ice is not open (summer, or dark and unlit)

    manager.sports_ice_open = True
    for step in range(3):
        manager.sim_time = step * 2.0
        manager.ensure_ice_skaters(car)
    players = [p for p in manager.pedestrians if p.activity and p.activity.plugin_id == "ice_hockey"]
    assert len(players) >= 2 and all(_inside(p) for p in players)

    for _ in range(100):  # 10 s of hockey: everyone stays on the ice, skating
        manager.sim_time += 0.1
        for player in players:
            manager._update_activity(player, 0.1)
    assert all(_inside(p) and p.activity is not None for p in players)

    manager.sports_ice_open = False  # dusk past 22:00, or a thaw
    for player in players:
        manager._update_activity(player, 0.1)
    assert all(p.activity is None for p in players)


def test_a_frozen_pitch_gets_skaters():
    manager = _manager("pitch")
    manager.sports_ice_open = True
    manager.ensure_ice_skaters(Car(x=20.0, y=0.0, heading=0.0, speed=0.0))
    assert [p.activity.plugin_id for p in manager.pedestrians] == ["ice_skating"]


def test_an_ice_rink_is_closed_you_crash_into_its_boards():
    taxi = TaxiManager([Way([(0.0, 0.0), (100.0, 0.0)], "residential", 4.0)])
    rink = Scenery(RINK, "ice_rink", bbox=(0.0, 10.0, 40.0, 30.0))
    car = Car(x=20.0, y=11.0, heading=1.57, speed=8.0)
    assert taxi.check_fence_collision(car, [rink], 1.0, previous_position=(20.0, 6.0))
    assert (car.x, car.y, car.speed) == (20.0, 6.0, 0.0)
