from types import SimpleNamespace

from theroadragetrip import map_chunks


def test_plan_loads_the_square_around_the_player_nearest_first():
    to_load, to_drop = map_chunks.plan(set(), (0, 0), load_radius=1)
    assert to_load[0] == "0_0" and len(to_load) == 9 and to_drop == []


def test_plan_skips_loaded_chunks_and_drops_only_beyond_the_unload_radius():
    loaded = {"0_0", "1_0", "5_0", "-3_0"}
    to_load, to_drop = map_chunks.plan(loaded, (0, 0), load_radius=1, unload_radius=2)
    assert "0_0" not in to_load and "1_0" not in to_load
    assert to_drop == ["-3_0", "5_0"]


def test_a_feature_is_in_every_chunk_it_touches_and_negative_cells_work():
    way = SimpleNamespace(points_m=[(-10.0, 5.0), (510.0, 5.0)], half_width_m=3.0, highway="primary",
                          is_drivable=True, layer=0)
    world = SimpleNamespace(ways=[way], railways=[], waters=[], buildings=[])
    index = map_chunks.ChunkIndex(world, size=500.0)
    assert len(index.message("-1_0")["roads"]) == 1 and len(index.message("1_0")["roads"]) == 1
    assert index.message("0_0")["roads"] == []  # no vertex there (see module docstring)
    assert index.message("1_0")["bounds"] == [500.0, 0.0, 1000.0, 500.0]
