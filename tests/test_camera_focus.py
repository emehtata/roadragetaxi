from types import SimpleNamespace

from theroadragetrip.camera_focus import ease_camera, focus_target, npc_at_screen_position, pan


def test_ctrl_drag_pans_with_the_pointer():
    focus = pan(None, 100.0, 200.0, 0, 0, 2.0)
    assert focus == ("pan", 100.0, 200.0)
    focus = pan(focus, 0, 0, 20, -10, 2.0)  # drag right and up: the view moves left and down
    assert focus == ("pan", 90.0, 195.0)
    assert focus_target(focus, [], []) == (90.0, 195.0)


def test_following_a_resident_then_the_car_they_ride_then_losing_them():
    walker = SimpleNamespace(resident_id=7, x=5.0, y=6.0)
    car = SimpleNamespace(x=50.0, y=60.0, occupant_ids=[7], current_driver_id=None)
    assert focus_target(("resident", 7), [walker], [car]) == (5.0, 6.0)
    assert focus_target(("resident", 7), [], [car]) == (50.0, 60.0)  # got into a car
    assert focus_target(("resident", 7), [], []) is None


def test_following_an_npc_until_it_leaves_the_world():
    npc = SimpleNamespace(x=1.0, y=2.0, length_m=4.5)
    assert focus_target(("npc", npc), [], [npc]) == (1.0, 2.0)
    assert focus_target(("npc", npc), [], []) is None


def test_clicking_selects_the_npc_under_the_pointer():
    near = SimpleNamespace(x=10.0, y=0.0, length_m=4.5)
    far = SimpleNamespace(x=60.0, y=0.0, length_m=4.5)
    # camera at origin, 2 px/m, 200x200 screen: near at screen (120, 100)
    assert npc_at_screen_position([far, near], (122, 101), 0.0, 0.0, 2.0, 200, 200) is near
    assert npc_at_screen_position([far, near], (20, 20), 0.0, 0.0, 2.0, 200, 200) is None


def test_follow_camera_eases_onto_its_target():
    x, y = 0.0, 0.0
    for _ in range(120):
        x, y = ease_camera(x, y, (100.0, -50.0), 1 / 60)
    assert abs(x - 100.0) < 0.1 and abs(y + 50.0) < 0.1
