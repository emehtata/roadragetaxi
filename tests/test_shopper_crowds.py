import subprocess
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

from theroadragetrip.shopper_crowds import MAX_PER_STORE, MAX_SHOPPERS, ShopperCrowds, cart_for


class Pedestrians:
    def __init__(self, buildings):
        self.pedestrians = []
        self.buildings = buildings
        self.next_id = 0

    def spawn_pedestrian_at_door(self, x, y):
        self.next_id += 1
        return SimpleNamespace(x=x, y=y, resident_id=self.next_id, cart=False)

    spawn_pedestrian_at = spawn_pedestrian_at_door

    def add_pedestrian(self, pedestrian):
        self.pedestrians.append(pedestrian)
        return True


def store(x, shop="supermarket"):
    points = [(x, 0.0), (x + 20, 0.0), (x + 20, 20.0), (x, 20.0)]
    return SimpleNamespace(shop_type=shop, points_m=points, bbox=(x, 0.0, x + 20, 20.0), entrances=[(x + 10, 0.0)])


def parking(x):
    return SimpleNamespace(kind="parking", points_m=[(x, -40.0), (x + 20, -40.0), (x + 20, -20.0), (x, -20.0)])


NOON = datetime(2026, 11, 14, 12, 0)


def run(crowds, now, position, times=1):
    for step in range(times):
        crowds.update(now + timedelta(seconds=30 * step), position)


def test_shoppers_only_near_store_with_parking():
    pedestrians = Pedestrians([store(0.0), store(500.0), store(1000.0, "clothes")])
    crowds = ShopperCrowds(pedestrians, [parking(0.0), parking(1000.0)])
    run(crowds, NOON, (10.0, 0.0))
    assert len(pedestrians.pedestrians) == MAX_PER_STORE
    pedestrians.pedestrians.clear()
    run(crowds, NOON + timedelta(hours=1), (510.0, 0.0))
    run(crowds, NOON + timedelta(hours=2), (1010.0, 0.0))
    assert pedestrians.pedestrians == []


def test_shopper_caps_per_store_and_map():
    stores = [store(x * 30.0) for x in range(40)]
    pedestrians = Pedestrians(stores)
    crowds = ShopperCrowds(pedestrians, [parking(x * 30.0) for x in range(40)])
    crowds.spawn_radius_m = 1e9
    run(crowds, NOON, (0.0, 0.0), times=5)
    assert len(pedestrians.pedestrians) == MAX_SHOPPERS
    for entry in crowds.stores:
        assert len(entry.shoppers) <= MAX_PER_STORE
    leaver = pedestrians.pedestrians[0]
    leaver.x += 1000.0  # walked away: removed and replaced
    run(crowds, NOON + timedelta(minutes=10), (0.0, 0.0))
    assert leaver not in pedestrians.pedestrians and len(pedestrians.pedestrians) == MAX_SHOPPERS


def test_cart_deterministic_per_id():
    values = [cart_for(i) for i in range(200)]
    assert 70 < sum(values) < 130
    other = subprocess.run([sys.executable, "-c", "from theroadragetrip.shopper_crowds import cart_for;"
                            "print(''.join('1' if cart_for(i) else '0' for i in range(200)))"],
                           capture_output=True, text=True, check=True).stdout.strip()
    assert other == "".join("1" if v else "0" for v in values)
    from theroadragetrip.protocol import _pedestrian_to_dict
    assert "cart" not in _pedestrian_to_dict(SimpleNamespace(
        resident_id=1, x=0, y=0, heading=0, radius_m=0.4, color=(1, 1, 1), state="", animation_state="",
        animation_time=0, curse_timer=0, curse_text="", mood="", is_cyclist=False, cart=False))


def test_no_shoppers_at_night():
    pedestrians = Pedestrians([store(0.0)])
    crowds = ShopperCrowds(pedestrians, [parking(0.0)])
    run(crowds, datetime(2026, 11, 14, 23, 0), (10.0, 0.0))
    run(crowds, datetime(2026, 11, 15, 6, 59), (10.0, 0.0))
    assert pedestrians.pedestrians == []
