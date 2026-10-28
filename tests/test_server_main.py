import configparser
from types import SimpleNamespace

from theroadragetrip.server import __main__ as server_main


def test_the_server_process_tunes_the_interpreter_before_the_world_loads(monkeypatch):
    calls = []
    args = SimpleNamespace(list_cities=False, list_city_locations=False, clear_cache=False, reset_home=False, parent_pid=None, log_level="WARNING")
    monkeypatch.setattr(server_main, "tune_interpreter", lambda: calls.append("tune"))
    monkeypatch.setattr(server_main, "parse_server_args", lambda: (args, configparser.ConfigParser()))
    monkeypatch.setattr(server_main, "configure_logging", lambda *a, **k: None)
    monkeypatch.setattr(server_main, "run_server", lambda *a: calls.append("load") or SimpleNamespace(
        chosen_city="Oulu", tick_rate=30.0, run_forever=lambda: None))
    server_main.main()
    assert calls == ["tune", "load"]


def test_preset_accepts_any_catalog_municipality(monkeypatch):
    """The map picker passes the pin's nearest municipality, not only menu cities."""
    from theroadragetrip.server.cli import parse_server_args
    monkeypatch.setattr("sys.argv", ["server", "--preset", "Muurame"])
    assert parse_server_args()[0].preset == "Muurame"


def test_launcher_queries_print_ascii_json(monkeypatch, capsys):
    """Godot reads these lines in the Windows code page: Sysmä came out as SysmÃ¤."""
    import json
    args = SimpleNamespace(list_cities=False, list_city_locations=True, list_saves=False)
    monkeypatch.setattr(server_main, "parse_server_args", lambda: (args, configparser.ConfigParser()))
    server_main.main()
    line = capsys.readouterr().out.strip()
    assert line.isascii() and "Sysmä" in [row["name"] for row in json.loads(line)]
