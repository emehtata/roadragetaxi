from types import SimpleNamespace

from theroadragetrip.npc import _ROUTE_NODE_GRID_CELL_M, through_road_first


class Grid:
    def __init__(self, ways):
        self.ways = ways

    def ways_in_rect(self, *_):
        return self.ways


def test_the_players_road_nodes_come_first_even_past_the_spawn_ring():
    trunk = SimpleNamespace(ref="22", highway="trunk", points_m=[(-300.0, 0.0), (300.0, 0.0)])
    side = SimpleNamespace(ref=None, highway="residential", points_m=[(0.0, 150.0), (0.0, 200.0)])
    nodes = [(-300.0, 0.0, 0), (300.0, 0.0, 0), (0.0, 150.0, 0), (0.0, 200.0, 0)]
    grid = {}
    for i, (x, y, _) in enumerate(nodes):
        grid.setdefault((x // _ROUTE_NODE_GRID_CELL_M, y // _ROUTE_NODE_GRID_CELL_M), []).append(i)
    ordered = through_road_first(nodes, grid, [2, 3], trunk, Grid([trunk, side]), 0.0, 0.0, 400.0)
    assert set(ordered[:2]) == {0, 1} and ordered[2:] == [2, 3]
    assert through_road_first(nodes, grid, [2, 3], None, Grid([trunk]), 0.0, 0.0, 400.0) == [2, 3]
