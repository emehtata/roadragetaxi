"""Tests for autonomous NPC traffic manager."""
import math
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car
from theroadragetrip.traffic import NPCCar, TrafficManager


def test_npc_traffic_spawning_and_movement():
    # Two connected way segments
    way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main St 1",
    )
    way2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main St 2",
    )
    ways = [way1, way2]

    traffic_mgr = TrafficManager(ways, target_count=5, spawn_radius_m=300.0, despawn_radius_m=500.0)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    # Initial update spawns NPCs
    traffic_mgr.update(player, dt=0.1)
    assert len(traffic_mgr.npcs) == 5

    # Check each NPC has valid position and color
    for npc in traffic_mgr.npcs:
        assert isinstance(npc, NPCCar)
        assert 0.0 <= npc.x <= 200.0
        assert -5.0 <= npc.y <= 5.0
        assert len(npc.color) == 3

    # Step simulation multiple frames and verify movement
    initial_positions = [(npc.x, npc.y) for npc in traffic_mgr.npcs]
    for _ in range(10):
        traffic_mgr.update(player, dt=0.1)

    # At least some NPCs have moved
    moved_count = sum(
        1 for i, npc in enumerate(traffic_mgr.npcs)
        if (npc.x, npc.y) != initial_positions[i]
    )
    assert moved_count > 0


def test_npc_right_side_and_overtaking():
    way = Way(
        points_m=[(0.0, 0.0), (500.0, 0.0)],
        highway="primary",
        half_width_m=6.0,
        name="Two-way Road",
        oneway=0,
    )
    ways = [way]
    traffic_mgr = TrafficManager(ways, target_count=2, spawn_radius_m=300.0, despawn_radius_m=500.0)

    # Spawn NPC
    npc = traffic_mgr.spawn_npc(100.0, 0.0)
    assert npc is not None
    assert npc.lane_offset > 0  # drives on the right side of the centerline

    # Test overtaking offset
    from theroadragetrip.traffic import compute_desired_lane_offset
    normal_offset = compute_desired_lane_offset(way, is_overtaking=False)
    overtake_offset = compute_desired_lane_offset(way, is_overtaking=True)
    assert normal_offset > 0
    assert overtake_offset < 0  # shifts left to overtake


def test_npc_despawning_when_far():
    way = Way(
        points_m=[(0.0, 0.0), (1000.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Long Highway",
    )
    ways = [way]
    traffic_mgr = TrafficManager(ways, target_count=3, spawn_radius_m=200.0, despawn_radius_m=300.0)

    player = Car(x=0.0, y=0.0, heading=0.0, speed=0.0)
    traffic_mgr.update(player, dt=0.1)
    assert len(traffic_mgr.npcs) == 3

    # Move player far away
    player.x = 5000.0
    traffic_mgr.update(player, dt=0.1)
    # Old NPCs despawned and new ones spawned around the player's new position
    for npc in traffic_mgr.npcs:
        assert math.hypot(npc.x - player.x, npc.y - player.y) <= 400.0


def test_npc_avoids_180_degree_u_turns_at_junction():
    # + shape intersection:
    # East-West road: (-100, 0) to (100, 0)
    # North-South road: (0, -100) to (0, 100)
    ew_way = Way(
        points_m=[(-100.0, 0.0), (0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="EW Street",
        oneway=0,
    )
    ns_way = Way(
        points_m=[(0.0, -100.0), (0.0, 0.0), (0.0, 100.0)],
        highway="primary",
        half_width_m=4.0,
        name="NS Street",
        oneway=0,
    )
    ways = [ew_way, ns_way]
    traffic_mgr = TrafficManager(ways)

    # Car approaching junction (0, 0) from west moving east (heading = 0.0)
    # Incoming heading is 0.0 (east)
    chosen_routes = []
    for _ in range(50):
        next_route = traffic_mgr._find_next_way_and_segment(
            ew_way, (0.0, 0.0), incoming_heading=0.0
        )
        assert next_route is not None
        cand_way, cand_seg_idx, cand_dir = next_route
        # Check angle
        cand_pts = cand_way.points_m
        if cand_dir == 1:
            p1, p2 = cand_pts[cand_seg_idx], cand_pts[cand_seg_idx + 1]
        else:
            p1, p2 = cand_pts[cand_seg_idx + 1], cand_pts[cand_seg_idx]
        out_heading = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
        angle_diff = abs((out_heading - 0.0 + math.pi) % (2 * math.pi) - math.pi)
        # Must not turn ~180 degrees back west
        assert angle_diff < math.radians(135)
        chosen_routes.append(next_route)

    # Single isolated road: 180 turn is the ONLY option, so it should allow it
    dead_end_way = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="residential",
        half_width_m=3.0,
        name="Dead End",
        oneway=0,
    )
    traffic_mgr_single = TrafficManager([dead_end_way])
    rev_route = traffic_mgr_single._find_next_way_and_segment(
        dead_end_way, (100.0, 0.0), incoming_heading=0.0
    )
    # When at (100, 0), the only way to go is backward (dir=-1, segment 0)
    assert rev_route is not None
    assert rev_route[0] is dead_end_way
    assert rev_route[2] == -1


def test_player_and_npc_car_crash_and_penalty():
    from theroadragetrip.taxi import TaxiManager

    taxi_mgr = TaxiManager(ways=[])
    taxi_mgr.total_score = 500

    player = Car(x=10.0, y=0.0, heading=0.0, speed=10.0, length_m=4.0, width_m=1.8)
    # NPC right at (12.0, 0.0) -> overlaps with 4m player car
    npc = NPCCar(
        x=12.0,
        y=0.0,
        heading=0.0,
        speed=5.0,
        way=Way(points_m=[(0.0, 0.0), (100.0, 0.0)], highway="primary", half_width_m=4.0),
        segment_idx=0,
        direction=1,
        target_speed=10.0,
        color=(100, 100, 100),
        length_m=4.0,
        width_m=1.8,
    )

    crashed = taxi_mgr.check_car_collision(player, [npc], sim_time=1.0, penalty=150)
    assert crashed is True
    assert taxi_mgr.total_score == 350
    assert "Crash!" in taxi_mgr.notification_msg

    # Cooldown prevents repeated penalties in rapid succession
    crashed2 = taxi_mgr.check_car_collision(player, [npc], sim_time=1.2, penalty=150)
    assert taxi_mgr.total_score == 350


def test_npc_does_not_spawn_on_orphaned_road_segment():
    # Main connected road network
    main_way1 = Way(
        points_m=[(0.0, 0.0), (100.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main Road 1",
    )
    main_way2 = Way(
        points_m=[(100.0, 0.0), (200.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Main Road 2",
    )
    # Orphaned disconnected road segment far away
    orphan_way = Way(
        points_m=[(50.0, 50.0), (70.0, 50.0)],
        highway="residential",
        half_width_m=4.0,
        name="Orphan Road",
    )
    ways = [main_way1, main_way2, orphan_way]

    traffic_mgr = TrafficManager(ways, target_count=5, spawn_radius_m=300.0, despawn_radius_m=500.0)
    player = Car(x=50.0, y=0.0, heading=0.0, speed=0.0)

    traffic_mgr.update(player, dt=0.1)

    # NPCs must only be on the main connected road network, none on the orphaned segment
    assert len(traffic_mgr.npcs) == 5
    for npc in traffic_mgr.npcs:
        assert npc.way is not orphan_way
        assert npc.way in (main_way1, main_way2)


def test_npc_avoids_colliding_with_leading_npc():
    way = Way(
        points_m=[(0.0, 0.0), (300.0, 0.0)],
        highway="primary",
        half_width_m=4.0,
        name="Straight Road",
    )
    traffic_mgr = TrafficManager([way], target_count=2)

    # Lead car (slow or stopped) at x=50.0
    lead_npc = NPCCar(
        x=50.0,
        y=0.0,
        heading=0.0,
        speed=0.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=0.0,
        color=(100, 100, 100),
        length_m=4.0,
        width_m=1.8,
    )
    # Following car approaching from x=40.0 with speed 12.0 m/s
    following_npc = NPCCar(
        x=40.0,
        y=0.0,
        heading=0.0,
        speed=12.0,
        way=way,
        segment_idx=0,
        direction=1,
        target_speed=12.0,
        color=(200, 50, 50),
        length_m=4.0,
        width_m=1.8,
    )

    traffic_mgr.npcs = [lead_npc, following_npc]
    player = Car(x=200.0, y=200.0, heading=0.0, speed=0.0)

    # Update simulation
    traffic_mgr.update(player, dt=0.1)

    # Following car should brake hard to avoid collision
    assert following_npc.speed < 12.0
    # Run multiple steps to ensure distance is maintained
    for _ in range(15):
        traffic_mgr.update(player, dt=0.1)

    # Following car stopped or maintained safe distance behind lead car
    assert following_npc.x < lead_npc.x
    assert math.hypot(lead_npc.x - following_npc.x, lead_npc.y - following_npc.y) >= 3.5

