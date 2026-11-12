"""First-person walking (fps-3d-view spec, phase 1): the server moves the
on-foot player relative to the client's look heading, limits walking and
sprint speed, and blocks walls and vehicles."""
import math
from types import SimpleNamespace

from theroadragetrip.pedestrian import PlayerPedestrian
from theroadragetrip.protocol import command_from_message
from theroadragetrip.simulation import (FPS_SPRINT_SPEED_MPS, FPS_WALK_SPEED_MPS, fps_walk_step,
                                        point_in_vehicle)

OPEN = lambda x, y: False  # noqa: E731


def _walk(ped, seconds, blocked=OPEN, **command):
    for _ in range(int(seconds * 30)):
        fps_walk_step(ped, command.get("forward", 0.0), command.get("strafe", 0.0),
                      command.get("look", 0.0), command.get("sprint", False), 1 / 30, blocked)


def test_walks_where_the_camera_looks_at_walking_speed():
    ped = PlayerPedestrian(0.0, 0.0)
    _walk(ped, 0.1, forward=1.0, look=math.pi / 2)
    assert 0.0 < ped.speed < FPS_WALK_SPEED_MPS  # accelerating, not jumping to full speed
    _walk(ped, 3.0, forward=1.0, look=math.pi / 2)
    assert math.isclose(ped.speed, FPS_WALK_SPEED_MPS, rel_tol=1e-6)
    assert ped.heading == math.pi / 2 and abs(ped.x) < 1e-6 and ped.y > 3.0


def test_strafes_sideways_and_diagonal_is_not_faster():
    ped = PlayerPedestrian(0.0, 0.0)
    _walk(ped, 3.0, strafe=1.0, look=0.0)  # right of east, in server (y-up) axes: south
    assert abs(ped.x) < 1e-6 and ped.y < -3.0
    _walk(ped, 3.0, forward=1.0, strafe=1.0, look=0.0)
    assert ped.speed <= FPS_WALK_SPEED_MPS + 1e-6


def test_sprint_is_faster_but_limited_and_stops_smoothly():
    ped = PlayerPedestrian(0.0, 0.0)
    _walk(ped, 4.0, forward=1.0, sprint=True)
    assert math.isclose(ped.speed, FPS_SPRINT_SPEED_MPS, rel_tol=1e-6)
    _walk(ped, 0.1)
    assert 0.0 < ped.speed < FPS_SPRINT_SPEED_MPS
    _walk(ped, 3.0)
    assert ped.speed == 0.0


def test_walls_block_and_the_player_slides():
    wall = lambda x, y: x > 1.0  # noqa: E731
    ped = PlayerPedestrian(0.0, 0.0)
    _walk(ped, 3.0, wall, forward=1.0, strafe=-1.0, look=0.0)  # north-east, into the wall
    assert ped.x <= 1.0 and ped.y > 1.0


def test_vehicle_footprint_blocks():
    car = SimpleNamespace(x=5.0, y=0.0, heading=math.pi / 2, length_m=4.0, width_m=1.8)
    assert point_in_vehicle(5.0, 1.9, car, 0.3) and not point_in_vehicle(6.3, 0.0, car, 0.3)
    ped = PlayerPedestrian(0.0, 0.0)
    _walk(ped, 5.0, lambda x, y: point_in_vehicle(x, y, car, 0.3), forward=1.0)
    assert 3.0 < ped.x < 3.8


def test_protocol_reads_look_heading_and_strafe_and_rejects_junk():
    command, _ = command_from_message({"command": {"look_heading": 1.0, "strafe": 5.0}})
    assert command.look_heading == 1.0 and command.strafe == 1.0
    command, _ = command_from_message({"command": {"look_heading": float("nan"), "strafe": "x"}})
    assert command.look_heading is None and command.strafe == 0.0


def test_the_walker_figure_faces_where_it_moves_not_where_it_looks():
    from theroadragetrip.protocol import player_walker_dict
    ped = PlayerPedestrian(0.0, 0.0)
    fps_walk_step(ped, 0.0, 1.0, math.pi / 2, False, 1.0, lambda *_: False)  # looking north, strafing right
    row = player_walker_dict(ped)
    assert row["heading"] == math.pi / 2 and abs(row["facing"]) < 1e-6 and row["speed"] > 1.0
    ped.velocity, ped.speed = (0.0, 0.0), 0.0
    assert player_walker_dict(ped)["facing"] == math.pi / 2  # standing: the way they look


def test_the_walker_slides_along_a_diagonal_wall():
    from theroadragetrip.simulation import walk_blocked_by_walls
    x, y = walk_blocked_by_walls(4.99, 4.99, 0.1, 0.0, lambda px, py: px + py > 10.0)  # a 45 degree facade ahead-left
    assert x > 4.99 and y < 4.99 and x + y <= 10.0
