from theroadragetrip.main import _respawn_allowed


def test_respawn_is_blocked_while_driver_is_on_foot():
    assert _respawn_allowed(True) is False
    assert _respawn_allowed(False) is True
