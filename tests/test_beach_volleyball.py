"""Mapped sand courts, bounded team formation, rallies and beach-weather cleanup."""
import pytest
from shapely.geometry import Point, Polygon

from theroadragetrip import protocol
from theroadragetrip.activities.plugins.tennis import court_frame
from theroadragetrip.map_chunks import ChunkIndex
from theroadragetrip.osm import Scenery, Way, build_ways
from theroadragetrip.pedestrian import PedestrianManager, SPORTS_SPAWNS_PER_CHECK
from theroadragetrip.physics import Car
from theroadragetrip.world_cache import BinaryWorldCacheLoader, BinaryWorldCacheWriter


def volleyball_world():
    court = Scenery([(-8,-4),(8,-4),(8,4),(-8,4)], "pitch", sport="beachvolleyball", bbox=(-8,-4,8,4))
    court.volleyball_frame = court_frame(court.points_m)
    way = Way([(-20,-12),(20,-12)], "footway", 1.5)
    manager = PedestrianManager([way], target_count=0, sceneries=[court])
    return manager, court, Car(x=0,y=-15,heading=0,speed=0), (-30,-20,30,20)


def populate(manager, car, view):
    for _ in range(4):
        before = len(manager.pedestrians)
        manager.sim_time += 2
        manager.ensure_sports_players(car, view)
        assert len(manager.pedestrians) - before <= SPORTS_SPAWNS_PER_CHECK


def test_two_teams_rally_inside_court_and_stop_with_beach_weather():
    manager, court, car, view = volleyball_world()
    populate(manager,car,view)
    assert not manager.pedestrians
    manager.beach_open = True
    populate(manager,car,view)
    assert len(manager.pedestrians) == 4
    assert {p.activity.plugin_id for p in manager.pedestrians} == {"beach_volleyball"}
    assert len(protocol.shown_pedestrians(manager,0,0)) == 4  # visible even with a zero ordinary population target
    group = manager.pedestrians[0].activity.group
    assert len({id(p.activity.group) for p in manager.pedestrians}) == 1
    swings, balls, positions = set(), set(), set()
    court_shape = Polygon(court.points_m)
    for _ in range(240):
        manager.sim_time += .05
        for p in manager.pedestrians:
            manager._update_activity(p,.05)
            assert court_shape.contains(Point(p.x,p.y))
            if p.stick_swing > .2:
                swings.add(p.resident_id)
            positions.add((p.resident_id,round(p.x,2),round(p.y,2)))
        ball_rows = [row['beach_ball'] for p in manager.pedestrians
                     if 'beach_ball' in (row := protocol._pedestrian_to_dict(p))]
        assert len(ball_rows) == 1
        x,y,height = ball_rows[0]
        assert court_shape.contains(Point(x,y))
        assert 1.49 <= height <= 4.51
        balls.add((round(x,2),round(y,2)))
        # Near the centre net the ball must clear its 2.43 m height.
        if abs(x) < .5:
            assert height > 2.43
    assert len(swings) == 4 and len(balls) > 100 and len(positions) > 40
    manager.beach_open = False
    for p in manager.pedestrians:
        manager._update_activity(p,.1)
    assert all(p.activity is None and p.stick_swing == 0 for p in manager.pedestrians)
    assert not group.member_resident_ids


def test_wait_for_four_players_and_clean_up_a_court_outside_view():
    manager,court,car,view = volleyball_world()
    manager.beach_open = True
    manager.sim_time = 2
    manager.ensure_sports_players(car,view)
    assert len(manager.pedestrians) == 2
    group = manager.pedestrians[0].activity.group
    manager.sim_time += .1
    for p in manager.pedestrians:
        manager._update_activity(p,.1)
        assert p.animation_state == 'idle'
        assert 'beach_ball' not in protocol._pedestrian_to_dict(p)
    manager.sim_time += 2
    manager.ensure_sports_players(car,(1000,1000,1100,1100))
    assert not manager.pedestrians and not group.member_resident_ids
    assert not manager.activity_manager._reservations


def test_missing_teammate_ends_the_whole_rally():
    manager,court,car,view = volleyball_world()
    manager.beach_open = True
    populate(manager,car,view)
    for p in manager.pedestrians:
        manager._update_activity(p,.1)
    group = manager.pedestrians[0].activity.group
    manager.pedestrians.pop()
    manager.sim_time += .1
    for p in manager.pedestrians:
        manager._update_activity(p,.1)
    assert all(p.activity is None for p in manager.pedestrians)


@pytest.mark.parametrize('tags,eligible',[
    ({},True),({'sport':'soccer;beachvolleyball'},True),
    ({'sport':'volleyball','surface':'sand'},True),({'sport':'volleyball'},False),
    ({'indoor':'yes'},False),({'indoor':'room'},False),({'covered':'yes'},False),
    ({'layer':'1'},False),({'layer':'-1'},False),({'level':'-1'},False),
])
@pytest.mark.parametrize('relation',[False,True])
def test_osm_courts_and_cached_chunk_geometry(tmp_path,tags,eligible,relation):
    nodes=[(60,25),(60,25.0003),(60.00008,25.0003),(60.00008,25)]
    elements=[dict(type='node',id=i,lat=lat,lon=lon) for i,(lat,lon) in enumerate(nodes,1)]
    court_tags={'leisure':'pitch','sport':'beachvolleyball',**tags}
    elements.append(dict(type='way',id=10,nodes=[1,2,3,4,1],tags={} if relation else court_tags))
    if relation:
        elements.append(dict(type='relation',id=11,tags={'type':'multipolygon',**court_tags},
                             members=[dict(type='way',ref=10,role='outer')]))
    world=build_ways(elements)
    court,=world.sceneries
    assert bool(court.volleyball_frame) is eligible
    assert not court.tennis_frame
    path=tmp_path/'volleyball.rwc'
    BinaryWorldCacheWriter().write(path,world,area_id='volleyball')
    loaded=BinaryWorldCacheLoader().load(path)
    assert loaded.sceneries[0].volleyball_frame == court.volleyball_frame
    chunks=ChunkIndex(loaded)._chunks.values()
    assert any(c['volleyball_courts'] for c in chunks) is eligible


def test_irregular_court_is_not_used():
    points=[(0,0),(16,0),(16,3),(3,3),(3,8),(0,8)]
    assert court_frame(points) == []
