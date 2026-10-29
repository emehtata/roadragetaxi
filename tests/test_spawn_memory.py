"""npc.SpawnMemory: half the spawns reuse points that worked, half explore; hopeless ones are skipped."""
import random

from theroadragetrip.npc import SpawnMemory

NODES = [(0.2, 0.0, 0), (10.0, 0.0, 0), (20.0, 0.0, 0), (30.0, 0.0, 0)]


def test_good_points_first_hopeless_ones_skipped_untried_kept():
    memory = SpawnMemory()
    memory.succeeded((30.0, 0.0))
    memory.failed((10.0, 0.0))
    memory.failed((10.0, 0.0))
    memory.failed((20.0, 0.0))  # once: still worth another try
    assert memory.order(NODES, [0, 1, 2, 3], rng=random.Random(0)) in ([3, 0, 2], [0, 2, 3])
    firsts = [memory.order(NODES, [0, 1, 2, 3], rng=random.Random(seed))[0] for seed in range(200)]
    assert 70 < firsts.count(3) < 130  # about half reuse the good point, half explore first


def test_a_point_that_once_worked_is_never_dropped_and_matches_by_whole_metres():
    memory = SpawnMemory()
    memory.succeeded((0.4, -0.3))  # node 0, as placed after a map sync renumbered it
    for _ in range(5):
        memory.failed((0.0, 0.0))
    assert memory.order(NODES, [1, 0], rng=random.Random(0)) in ([0, 1], [1, 0])  # kept, not skipped
