from datetime import date, timedelta
from types import SimpleNamespace

from theroadragetrip.arena_crowds import ArenaCrowds
from theroadragetrip.osm.models import Way


class Pedestrians:
    def __init__(self):
        self.pedestrians = []
        self.buildings = []
        self.entrance_locations = []
        self.residents = SimpleNamespace(get=lambda resident_id: None)

    def spawn_pedestrian_at(self, x, y, heading=0.0):
        return SimpleNamespace(x=x, y=y, held_by=None, wants_taxi=False, resident_id=1,
                               is_drunk=False, blood_alcohol_promille=0.0,
                               is_walking_to_taxi_stop=False,
                               way=Way([(0.0, 20.0), (40.0, 20.0)], "footway", 1.0), segment_idx=0)

    def add_pedestrian(self, pedestrian):
        self.pedestrians.append(pedestrian)

    def spawn_pedestrian_at_door(self, x, y):
        return self.spawn_pedestrian_at(x, y)

    def _taxi_stop_waiting_position(self, stand):
        return stand.x, stand.y

    def _footway_route_to(self, pedestrian, destination):
        return [(pedestrian.x, pedestrian.y), destination]


def fixture(start="2026-10-15T15:00:00Z", attendance=3000):
    return {"id": "game", "competition": "liiga", "start": start, "attendance": attendance,
            "home_team": "Kärpät", "away_team": "Sport",
            "venue": {"name": "Oulun jäähalli", "city": "Oulu", "latitude": 65.0, "longitude": 25.0}}


def test_arena_fills_during_hour_before_game_and_arrivals_go_inside_at_start():
    pedestrians = Pedestrians()
    crowds = ArenaCrowds(pedestrians, [], "oulu", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))
    start = crowds.events[0].start

    crowds.update(start - timedelta(minutes=30), (10.0, 20.0))
    assert len(pedestrians.pedestrians) == 10
    assert all(pedestrian.held_by is crowds for pedestrian in pedestrians.pedestrians)

    crowds.update(start, (10.0, 20.0))
    assert pedestrians.pedestrians == []


def test_spectators_leave_from_two_and_a_half_hours_and_some_seek_taxis():
    pedestrians = Pedestrians()
    stand = SimpleNamespace(x=30.0, y=40.0)
    crowds = ArenaCrowds(pedestrians, [stand], "Oulu", [fixture(attendance=6000)],
                         to_metres=lambda lat, lon: (10.0, 20.0), seed=1)
    departure = crowds.events[0].start + timedelta(hours=2, minutes=30)

    crowds.update(departure + timedelta(minutes=15), (10.0, 20.0))

    assert len(pedestrians.pedestrians) == 20
    assert any(pedestrian.wants_taxi for pedestrian in pedestrians.pedestrians)
    assert all(
        pedestrian.taxi_stop_target == (30.0, 40.0)
        for pedestrian in pedestrians.pedestrians if pedestrian.wants_taxi
    )


def test_spectators_leave_from_nearby_arena_doors():
    pedestrians = Pedestrians()
    pedestrians.entrance_locations = [(12.0, 20.0), (500.0, 500.0)]
    crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture()],
                         to_metres=lambda lat, lon: (10.0, 20.0))
    departure = crowds.events[0].start + timedelta(hours=2, minutes=30)

    crowds.update(departure + timedelta(minutes=15), (10.0, 20.0))

    assert len(pedestrians.pedestrians) == 10
    assert all((pedestrian.x, pedestrian.y) == (12.0, 20.0) for pedestrian in pedestrians.pedestrians)


def test_spectators_are_distributed_evenly_across_all_arena_doors():
    pedestrians = Pedestrians()
    doors = [(8.0, 20.0), (12.0, 20.0), (10.0, 18.0)]
    pedestrians.buildings = [SimpleNamespace(
        bbox=(5.0, 15.0, 15.0, 25.0),
        points_m=[(5.0, 15.0), (15.0, 15.0), (15.0, 25.0), (5.0, 25.0)],
        entrances=doors,
    )]
    crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture()],
                         to_metres=lambda lat, lon: (10.0, 20.0))
    departure = crowds.events[0].start + timedelta(hours=2, minutes=30)

    crowds.update(departure + timedelta(minutes=15), (10.0, 20.0))

    counts = {(x, y): sum((pedestrian.x, pedestrian.y) == (x, y)
                          for pedestrian in pedestrians.pedestrians) for x, y in doors}
    assert sorted(counts.values()) == [3, 3, 4]


def test_failed_arena_spawns_are_retried():
    pedestrians = Pedestrians()
    pedestrians.spawn_pedestrian_at = lambda *args, **kwargs: None
    crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture()],
                         to_metres=lambda lat, lon: (10.0, 20.0))
    departure = crowds.events[0].start + timedelta(hours=2, minutes=30)

    crowds.update(departure + timedelta(minutes=15), (10.0, 20.0))

    assert crowds.events[0].departures_spawned == 0


def test_friday_and_saturday_adult_spectators_are_more_likely_intoxicated():
    def departing(start):
        pedestrians = Pedestrians()
        pedestrians.residents = SimpleNamespace(
            get=lambda resident_id: SimpleNamespace(birth_date=date(2000, 1, 1)),
        )
        crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture(start=start)],
                             to_metres=lambda lat, lon: (10.0, 20.0))
        crowds.rng.random = lambda: 0.2
        crowds._spawn_departures(crowds.events[0], 1)
        return pedestrians.pedestrians[0]

    thursday = departing("2026-10-15T15:00:00Z")
    friday = departing("2026-10-16T15:00:00Z")
    saturday = departing("2026-10-17T15:00:00Z")

    assert not thursday.is_drunk
    assert friday.is_drunk and saturday.is_drunk


def test_arena_spectators_must_be_over_18_to_be_intoxicated():
    pedestrians = Pedestrians()
    pedestrians.residents = SimpleNamespace(
        get=lambda resident_id: SimpleNamespace(birth_date=date(2008, 10, 16)),
    )
    crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture(start="2026-10-16T15:00:00Z")],
                         to_metres=lambda lat, lon: (10.0, 20.0))
    crowds.rng.random = lambda: 0.0

    crowds._spawn_departures(crowds.events[0], 1)

    assert not pedestrians.pedestrians[0].is_drunk


def test_other_cities_and_distant_arenas_do_not_spawn_people():
    pedestrians = Pedestrians()
    crowds = ArenaCrowds(pedestrians, [], "Helsinki", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))
    assert crowds.events == []

    crowds = ArenaCrowds(pedestrians, [], "Oulu", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))
    crowds.update(crowds.events[0].start - timedelta(minutes=30), (1000.0, 1000.0))
    assert pedestrians.pedestrians == []


def test_game_day_schedule_uses_local_date_and_start_time():
    crowds = ArenaCrowds(Pedestrians(), [], "Oulu", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))

    games = crowds.schedule_on(crowds.events[0].start.date())

    assert [(game.home_team, game.away_team, game.start.strftime("%H:%M"), game.venue_name) for game in games] == [
        ("Kärpät", "Sport", "18:00", "Oulun jäähalli"),
    ]


def test_arena_lights_cover_arrivals_game_and_departures():
    crowds = ArenaCrowds(Pedestrians(), [], "Oulu", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))
    start = crowds.events[0].start

    assert not crowds.lights_on(start - timedelta(hours=1, seconds=1))
    assert crowds.lights_on(start - timedelta(hours=1))
    assert crowds.lights_on(start + timedelta(hours=2, minutes=59))
    assert not crowds.lights_on(start + timedelta(hours=3))


def test_the_game_is_heard_at_the_arena_only_while_it_is_played():
    crowds = ArenaCrowds(SimpleNamespace(pedestrians=[]), [], "Oulu", [fixture()], to_metres=lambda lat, lon: (10.0, 20.0))
    start = crowds.events[0].start
    assert crowds.games_in_progress(start - timedelta(minutes=1)) == []  # arrivals: no game yet
    assert crowds.games_in_progress(start) == [(10.0, 20.0)]
    assert crowds.games_in_progress(start + timedelta(hours=2, minutes=29)) == [(10.0, 20.0)]
    assert crowds.games_in_progress(start + timedelta(hours=2, minutes=30)) == []
