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
