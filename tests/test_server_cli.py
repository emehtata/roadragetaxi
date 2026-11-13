import sys

import pytest


def test_server_preset_choices_are_limited_to_configured_cities(monkeypatch, tmp_path):
    import theroadragetrip.server.cli as cli
    from theroadragetrip.config import load_config

    monkeypatch.setattr(cli, "load_config", lambda: load_config(tmp_path / "roadragetrip.ini"))
    monkeypatch.setattr(
        cli,
        "cities_from_config",
        lambda _config: ({"Oulu": (65.0, 25.0)}, {"oulu": (64.0, 24.0, 66.0, 26.0)}),
    )
    monkeypatch.setattr(sys, "argv", ["server", "--preset", "Nowhereville"])

    with pytest.raises(SystemExit):
        cli.parse_server_args()

    monkeypatch.setattr(sys, "argv", ["server", "--preset", "Oulu"])
    args, _config = cli.parse_server_args()
    assert args.preset == "Oulu"


def test_busy_port_exits_with_hint(monkeypatch, tmp_path, capsys):
    import json
    import socket
    from types import SimpleNamespace

    import theroadragetrip.server as server

    class Stub:  # skips the world build; start() is the real bind
        start = server.SimulationServer.start
        _on_client_connect = None

        def __init__(self, *_args, **_kwargs):
            pass

    monkeypatch.setattr(server, "SimulationServer", Stub)
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    holder.listen()
    port = holder.getsockname()[1]
    progress = tmp_path / "startup.json"
    try:
        with pytest.raises(SystemExit) as exited:
            server.run_server(SimpleNamespace(host="127.0.0.1", port=port, startup_progress=str(progress)), None)
    finally:
        holder.close()
    assert exited.value.code not in (0, None)
    err = capsys.readouterr().err
    assert "--port" in err and "Traceback" not in err
    assert json.loads(progress.read_text())["stage"] == "error"
