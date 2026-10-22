import math

from theroadragetrip.npc import NPCState, NPCVehicle, NPCVehicleManager, with_trailers
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.trailers import follow, hitch_point, pose
from theroadragetrip.vehicles.base import vehicle_definition

CARAVAN = vehicle_definition("car_caravan").trailer


def test_a_trailer_swings_in_behind_on_a_turn_not_rigidly():
    """Driving east, then turning north: the caravan lags the car's heading,
    cuts the corner, and straightens out on the new road."""
    x, y, heading, axle = 0.0, 0.0, 0.0, None
    path = [(step * 0.5, 0.0, 0.0) for step in range(40)] + [
        (20.0 + 8 * math.sin(a / 20 * math.pi / 2), 8 - 8 * math.cos(a / 20 * math.pi / 2), a / 20 * math.pi / 2)
        for a in range(1, 21)] + [(28.0, 8.0 + step * 0.5, math.pi / 2) for step in range(1, 60)]
    lag = []
    for x, y, heading in path:
        hitch = hitch_point(x, y, heading, 4.3)
        axle = follow(hitch, axle, heading, CARAVAN)
        assert math.dist(hitch, axle) == __import__("pytest").approx(CARAVAN.drawbar_m + CARAVAN.axle_m)
        lag.append(heading - pose(hitch, axle, CARAVAN)[2])
    assert max(lag) > 0.3  # mid-turn the caravan still points well behind the car's heading: it swings
    assert abs(lag[-1]) < 0.02  # and it straightens out behind on the new road


def test_a_moved_vehicle_gets_its_trailer_straight_behind():
    hitch = hitch_point(100.0, 0.0, 0.0, 4.3)
    axle = follow(hitch, (0.0, 0.0), 0.0, CARAVAN)  # was far away: placed anew
    assert axle == (hitch[0] - (CARAVAN.drawbar_m + CARAVAN.axle_m), hitch[1])


def _caravan_car(vehicle_id, x, heading=0.0, speed=0.0):
    return NPCVehicle(vehicle_id=vehicle_id, vehicle_type="car_caravan",
                      car=Car(x=x, y=0.0, heading=heading, speed=speed, length_m=4.3, width_m=1.8), state=NPCState.CRUISING)


def test_the_caravan_is_a_body_others_follow_and_collide_with():
    towing = _caravan_car(1, 20.0)
    towing.update_trailer()
    trailer = towing.trailer_body()
    assert trailer.tow is towing and trailer.x < 20.0 - 4.3 / 2 - CARAVAN.drawbar_m  # behind the car, apart from it
    assert trailer in with_trailers([towing])  # following traffic sees it as an obstacle
    # A car driving into the caravan (not the towing car) has hit that vehicle.
    manager = NPCVehicleManager(target_count=2)
    other = NPCVehicle(vehicle_id=2, car=Car(x=trailer.x - 1.0, y=0.0, heading=0.0, speed=10.0), state=NPCState.CRUISING)
    manager.vehicles.extend([towing, other])
    assert manager._check_vehicle_collision(other, with_trailers([towing]), ResidentManager(), None, sim_time=1.0)
    assert towing.state == NPCState.CRASHED and other.state == NPCState.CRASHED
