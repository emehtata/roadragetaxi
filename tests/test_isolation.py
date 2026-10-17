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
