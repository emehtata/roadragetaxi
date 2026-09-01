"""Scalability checks for the NPC spatial partition."""
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip.traffic import NPCCar, TrafficManager


def test_npc_spatial_query_stays_local_as_population_grows():
    way = Way(
        points_m=[(0.0, 0.0), (10000.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    manager = TrafficManager([way], target_count=0)
    manager.npcs = [
        NPCCar(
            x=float(index * 40),
            y=0.0,
            heading=0.0,
            speed=8.0,
            way=way,
            segment_idx=0,
            direction=1,
            target_speed=12.0,
            color=(20, 20, 20),
        )
        for index in range(250)
    ]
    manager._build_npc_spatial_grid()

    nearby = manager.nearby_npcs_at(0.0, 0.0)

    assert len(manager.npcs) == 250
    assert 0 < len(nearby) < len(manager.npcs) / 4


def test_large_population_update_uses_spatial_grid_without_errors():
    way = Way(
        points_m=[(0.0, 0.0), (10000.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
    )
    manager = TrafficManager([way], target_count=0)
    manager.npcs = [
        NPCCar(
            x=float(index * 40),
            y=0.0,
            heading=0.0,
            speed=4.0,
            way=way,
            segment_idx=0,
            direction=1,
            target_speed=8.0,
            color=(20, 20, 20),
        )
        for index in range(250)
    ]

    manager.update(Car(0.0, 0.0, 0.0, 0.0), 0.05)

    assert manager._npc_grid
    assert all(npc.speed >= 0.0 for npc in manager.npcs)
