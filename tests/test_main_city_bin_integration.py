import configparser
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pytest

from theroadragetrip.main import _load_world
import theroadragetrip.main as main_module
from theroadragetrip.main.cli import parse_args
from theroadragetrip.osm.bin_source import CityBinUnavailableError
from theroadragetrip.osm.constants import DEFAULT_BBOX
from theroadragetrip.osm.models import Way


class _FakeClock:
    def tick(self, *_args, **_kwargs):
        return 0


def _build_args(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    config = configparser.ConfigParser()
    for section in ("game", "map", "traffic", "experimental", "cities"):
        config.add_section(section)
    return parse_args(config=config, city_names=["oulu"])


def _load_sample_world(monkeypatch, tmp_path, city_name, extra_args=("--use-prebuilt-roads",)):
    args = _build_args(monkeypatch, ["--use-sample", "--no-cache", *extra_args])
    return _load_world(
        city_name, city_name, DEFAULT_BBOX, {city_name: (65.0121, 25.4651)},
        screen=None, font=None, clock=_FakeClock(), args=args,
        force_refresh=True, overpass_endpoints=[], bus_stops_enabled=False,
        roadworks_enabled=False, career=None,
        career_file=tmp_path / "career.json",
        gig_odometer_file=tmp_path / "gig.json",
        language="en", headless=True,
    )


def test_predefined_city_with_bin_loads_from_binary(monkeypatch, tmp_path, caplog):
    # city_bin_available("oulu") is genuinely True (the real bundled
    # binary exists), but load_city_ways is mocked to a tiny synthetic
    # result here - this test is about _load_world's wiring (does it call
    # load_city_ways and substitute `ways` on success?), not about
    # decoding the real ~87k-node binary, which test_city_bin_source.py
    # already covers once.
    fake_ways = [
        Way(points_m=[(0.0, 0.0), (10.0, 0.0)], highway="residential", half_width_m=3.0, osm_id=1),
        Way(points_m=[(10.0, 0.0), (20.0, 0.0)], highway="service", half_width_m=2.0, osm_id=2),
    ]
    monkeypatch.setattr(main_module, "load_city_ways", lambda city, bin_path=None: (fake_ways, 3, 4, 0.001))

    with caplog.at_level(logging.INFO, logger="theroadragetrip.main"):
        world = _load_sample_world(monkeypatch, tmp_path, "oulu")

    bin_logs = [r.message for r in caplog.records if "Road network source: prebuilt binary" in r.message]
    assert bin_logs, "expected a 'Road network source: prebuilt binary' log line"
    assert "City: oulu" in bin_logs[0]
    assert "Ways: 2" in bin_logs[0]
    assert world.traffic_mgr is not None
    ways = world.traffic_mgr.ways
    # Drivable roads come only from the binary; the fetch's own
    # footways/paths (which the binary doesn't contain) are kept.
    assert {way.osm_id for way in ways if way.is_drivable} == {1, 2}
    assert any(not way.is_drivable for way in ways)


def test_broken_bin_falls_back_to_existing_osm_path(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(
        main_module, "load_city_ways",
        lambda city, bin_path=None: (_ for _ in ()).throw(CityBinUnavailableError("corrupt test binary")),
    )
    with caplog.at_level(logging.INFO, logger="theroadragetrip.main"):
        world = _load_sample_world(monkeypatch, tmp_path, "oulu")

    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("falling back to existing OSM/PBF road loading" in msg for msg in warnings)
    # The world must still load successfully (sample data), not crash.
    assert world.traffic_mgr is not None
    assert len(world.traffic_mgr.ways) > 0


def test_custom_city_without_bin_uses_existing_osm_path(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="theroadragetrip.main"):
        world = _load_sample_world(monkeypatch, tmp_path, "MyCustomCity")

    fallback_logs = [r.message for r in caplog.records if "existing OSM/PBF fallback" in r.message]
    assert fallback_logs, "expected a 'Road network source: existing OSM/PBF fallback' log line"
    assert "City: MyCustomCity" in fallback_logs[0]
    assert not any("Road network source: prebuilt binary" in r.message for r in caplog.records)
    assert world.traffic_mgr is not None


def test_prebuilt_roads_are_off_by_default(monkeypatch, tmp_path, caplog):
    """map.use_prebuilt_roads defaults to false: the binary is not even read."""
    monkeypatch.setattr(
        main_module, "load_city_ways",
        lambda *_a, **_k: pytest.fail("prebuilt road binary loaded although disabled"),
    )
    with caplog.at_level(logging.INFO, logger="theroadragetrip.main"):
        world = _load_sample_world(monkeypatch, tmp_path, "oulu", extra_args=())
    assert any("prebuilt binary disabled" in r.message for r in caplog.records)
    assert any(way.is_drivable for way in world.traffic_mgr.ways)
