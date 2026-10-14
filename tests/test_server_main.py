import configparser
from types import SimpleNamespace

from theroadragetrip.server import __main__ as server_main


def test_the_server_process_tunes_the_interpreter_before_the_world_loads(monkeypatch):
    calls = []
    args = SimpleNamespace(list_cities=False, list_city_locations=False, clear_cache=False, reset_home=False, log_level="WARNING")
    monkeypatch.setattr(server_main, "tune_interpreter", lambda: calls.append("tune"))
    monkeypatch.setattr(server_main, "parse_server_args", lambda: (args, configparser.ConfigParser()))
    monkeypatch.setattr(server_main, "configure_logging", lambda *a, **k: None)
    monkeypatch.setattr(server_main, "run_server", lambda *a: calls.append("load") or SimpleNamespace(
        chosen_city="Oulu", tick_rate=30.0, run_forever=lambda: None))
    server_main.main()
    assert calls == ["tune", "load"]
