"""The test suite's own guarantees (conftest.py): no live network, no
writes into the developer's real config or caches."""
import os
import socket

import pytest


def test_the_game_s_user_paths_are_a_throwaway_directory():
    from theroadragetrip.config import CONFIG_PATH
    from theroadragetrip.osm import CACHE_DIR
    from theroadragetrip.world_cache import default_world_cache_dir

    assert "rrt-test-home-" in os.environ["HOME"]
    for path in (CONFIG_PATH, CACHE_DIR, default_world_cache_dir()):
        assert "rrt-test-home-" in str(path)


def test_a_live_connection_fails_the_test():
    with pytest.raises(AssertionError, match="network"):
        socket.create_connection(("192.0.2.1", 80), timeout=0.1)  # TEST-NET-1: never routable


def test_an_empty_xdg_config_home_is_not_the_working_directory(monkeypatch):
    """Bug: XDG_CONFIG_HOME="" put the config and saves under the cwd."""
    from theroadragetrip.config import _default_config_path

    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setattr("sys.platform", "linux")
    assert _default_config_path().is_absolute()
