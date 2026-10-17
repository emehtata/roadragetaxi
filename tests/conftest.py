import ipaddress
import os
import socket
import sys
import tempfile

# Isolate every per-user path before the game is imported: its config,
# saves (career, gig odometer, homes), OSM and world caches and timetables
# are module-level paths read from these at import. Server subprocesses
# started by tests inherit them. Without this a test wrote into the
# player's real OSM cache.
_USER_DIRS = tempfile.TemporaryDirectory(prefix="rrt-test-home-")
for _name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "XDG_CACHE_HOME", "APPDATA", "LOCALAPPDATA"):
    os.environ[_name] = os.path.join(_USER_DIRS.name, _name.lower())
    os.makedirs(os.environ[_name], exist_ok=True)

# Ensure src/ is on sys.path so tests can import the package without installing it.
ROOT = os.path.dirname(os.path.dirname(__file__))
src = os.path.join(ROOT, "src")
if src not in sys.path:
    sys.path.insert(0, src)

import pytest


@pytest.fixture(autouse=True)
def _reset_overpass_endpoint_cooldowns():
    """Clear both Overpass endpoint-cooldown maps before every test.

    Keyed by URL, shared across the whole test process - without this, a
    test that hits e.g. "https://mirror.example/api" could inherit a
    cooldown (rate-limit or courtesy) another, unrelated test left behind
    for the same URL, spuriously changing which endpoint a later fetch
    picks.
    """
    from theroadragetrip.osm import overpass as _overpass

    _overpass._endpoint_cooldown_until.clear()
    _overpass._endpoint_last_contact.clear()
    yield


@pytest.fixture(autouse=True)
def _no_timetable_refresh(monkeypatch, tmp_path):
    """Tests use the bundled timetable and compositions and never download new ones."""
    from theroadragetrip import train_compositions, train_timetable, world_loader

    monkeypatch.setattr(train_timetable, "USER_TIMETABLE_PATH", tmp_path / "no-user-timetable.json.gz")
    monkeypatch.setattr(world_loader, "refresh_if_stale", lambda document: None)
    monkeypatch.setattr(train_compositions, "USER_COMPOSITIONS_PATH", tmp_path / "no-user-compositions.json.gz")
    monkeypatch.setattr(world_loader, "refresh_compositions_if_stale", lambda database: None)


@pytest.fixture
def kunnat_centres(monkeypatch):
    """Sysmä's and Helsinki's centres in map metres. Some test modules
    replace pyproj with a fake at import, which would mis-project the
    cached municipality centres (taxi.municipality_points)."""
    from theroadragetrip import taxi
    monkeypatch.setattr(taxi, "_municipality_points", [
        ("Sysmä", 429772.8, 6819445.3, 1793, None),
        ("Helsinki", 385700.4, 6672126.7, 690000, None),
    ])


_real_connect = socket.socket.connect


def _local_only_connect(sock, address):
    """Tests never reach a live service (Overpass, Digitraffic, FMI, tiles):
    a connection to anything but this machine fails the test."""
    host = address[0] if isinstance(address, tuple) else None
    if host is not None:
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise AssertionError(f"test tried to reach the network: {address!r} (fake the fetch instead)")
    return _real_connect(sock, address)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _local_only_connect)


TIMING_ATTEMPTS = 3


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"timing: a wall-clock budget test, run up to {TIMING_ATTEMPTS} times (TESTING.md)",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """A `timing` test passes when one of TIMING_ATTEMPTS runs meets its
    budget: a busy machine only ever adds time, a regression fails them all.
    Budget asserts in the fast suite failed now and then under load."""
    if pyfuncitem.get_closest_marker("timing") is None:
        return None
    arguments = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
    for attempt in range(TIMING_ATTEMPTS):
        try:
            pyfuncitem.obj(**arguments)
            return True
        except AssertionError:
            if attempt == TIMING_ATTEMPTS - 1:
                raise


@pytest.fixture(autouse=True)
def _close_started_servers(monkeypatch):
    """Close every simulation server a test starts, pass or fail: left
    open, each kept its world, port and threads for the rest of the run."""
    from theroadragetrip import server as server_module

    started = []
    real_run_server = server_module.run_server

    def run_server(*args, **kwargs):
        started.append(real_run_server(*args, **kwargs))
        return started[-1]

    monkeypatch.setattr(server_module, "run_server", run_server)
    yield
    for server in started:
        server.close()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """The random order's seed, also under -q (pytest-randomly prints it only
    in the header, which -q hides): rerun a failure with -p randomly
    --randomly-seed=N."""
    seed = getattr(config.option, "randomly_seed", None)
    if seed is not None and getattr(config.option, "randomly_reorganize", True):
        terminalreporter.write_line(f"random order: --randomly-seed={seed}")
