"""Tests for the NPC vehicle-type plugin system (.github/prompts/NPC-003.md)."""
import pytest

from theroadragetrip.vehicles.base import VehicleDefinition, VehiclePlugin
from theroadragetrip.vehicles.plugins import discover
from theroadragetrip.vehicles.plugins.bicycle import BicyclePlugin
from theroadragetrip.vehicles.plugins.bus import BusPlugin
from theroadragetrip.vehicles.plugins.car import CarPlugin
from theroadragetrip.vehicles.plugins.motorcycle import MotorcyclePlugin
from theroadragetrip.vehicles.plugins.truck import TruckPlugin
from theroadragetrip.vehicles.plugins.van import VanPlugin
from theroadragetrip.vehicles.registry import VehicleRegistry


def _stub_plugin(plugin_id: str) -> VehiclePlugin:
    plugin = VehiclePlugin()
    plugin.definition = VehicleDefinition(
        id=plugin_id, name=plugin_id, sprite_key="car", length_m=4.0, width_m=1.8, capacity=1,
    )
    return plugin


def test_registry_rejects_duplicate_ids():
    registry = VehicleRegistry()
    registry.register(_stub_plugin("dup"))
    with pytest.raises(ValueError):
        registry.register(_stub_plugin("dup"))


def test_registry_get_and_all_plugins():
    registry = VehicleRegistry()
    plugin = _stub_plugin("solo")
    registry.register(plugin)
    assert registry.get("solo") is plugin
    assert registry.get("missing") is None
    assert registry.all_plugins() == [plugin]


def test_discover_registers_all_built_in_plugins():
    registry = VehicleRegistry()
    discover(registry)
    assert {plugin.definition.id for plugin in registry.all_plugins()} == {
        "car", "van", "truck", "bus", "motorcycle", "bicycle",
    }


def test_discover_registers_built_ins_when_frozen_package_scan_is_empty(monkeypatch):
    import theroadragetrip.vehicles.plugins as plugins_pkg

    monkeypatch.setattr(plugins_pkg.pkgutil, "iter_modules", lambda *args, **kwargs: ())
    registry = VehicleRegistry()
    discover(registry)

    assert registry.get("car") is not None


def test_discover_skips_a_broken_plugin_module_and_keeps_the_rest(monkeypatch):
    import theroadragetrip.vehicles.plugins as plugins_pkg

    real_import_module = plugins_pkg.importlib.import_module

    def flaky_import(name, *args, **kwargs):
        if name.endswith("truck"):
            raise RuntimeError("simulated broken plugin")
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(plugins_pkg.importlib, "import_module", flaky_import)
    registry = VehicleRegistry()
    discover(registry)  # must not raise

    ids = {plugin.definition.id for plugin in registry.all_plugins()}
    assert "truck" not in ids
    assert {"car", "van", "bus", "motorcycle", "bicycle"} <= ids


@pytest.mark.parametrize(
    "plugin, expected",
    [
        (CarPlugin(), {"length_m": 4.3, "width_m": 1.8, "capacity": 5, "household_eligible": True, "is_road_vehicle": True}),
        (VanPlugin(), {"length_m": 5.2, "width_m": 2.0, "capacity": 8, "household_eligible": True, "is_road_vehicle": True}),
        (TruckPlugin(), {"length_m": 7.5, "width_m": 2.3, "capacity": 2, "household_eligible": False, "is_road_vehicle": True}),
        (BusPlugin(), {"length_m": 11.0, "width_m": 2.5, "capacity": 40, "household_eligible": False, "is_road_vehicle": True}),
        (MotorcyclePlugin(), {"length_m": 2.0, "width_m": 0.7, "capacity": 1, "household_eligible": True, "is_road_vehicle": True}),
        (BicyclePlugin(), {"length_m": 1.8, "width_m": 0.5, "capacity": 1, "household_eligible": False, "is_road_vehicle": False}),
    ],
)
def test_built_in_plugin_matches_its_table_row(plugin, expected):
    assert plugin.get_dimensions() == (expected["length_m"], expected["width_m"])
    assert plugin.get_passenger_capacity() == expected["capacity"]
    assert plugin.can_be_household_owned() == expected["household_eligible"]
    assert plugin.definition.is_road_vehicle == expected["is_road_vehicle"]


def test_bicycle_has_zero_traffic_weight_and_no_parking_requirement():
    """Bicycles are registered for capability-query completeness but never
    auto-spawned by NPCVehicleManager - pedestrian.py's CyclistManager
    already owns background bicycle traffic (see bicycle.py's docstring)."""
    plugin = BicyclePlugin()
    assert plugin.definition.traffic_weight == 0.0
    assert plugin.requires_parking() is False


def test_truck_and_bus_are_not_errand_eligible():
    assert TruckPlugin().can_be_used_for_errands() is False
    assert BusPlugin().can_be_used_for_errands() is False


def test_truck_and_bus_have_a_max_speed_cap():
    assert TruckPlugin().get_max_speed_kmh() is not None
    assert BusPlugin().get_max_speed_kmh() is not None


def test_car_has_no_max_speed_cap_beyond_the_road_limit():
    assert CarPlugin().get_max_speed_kmh() is None


def test_default_capability_queries_read_from_definition_without_overrides():
    """Every built-in plugin above is pure data (no method overrides) -
    this directly exercises VehiclePlugin's own default implementations,
    not a subclass's."""
    plugin = _stub_plugin("generic")
    assert plugin.has_driver_requirement() is True
    assert plugin.can_carry_passengers() is True
    assert plugin.can_be_used_for_errands() is True
    assert plugin.requires_parking() is True
    assert plugin.can_be_household_owned() is False
