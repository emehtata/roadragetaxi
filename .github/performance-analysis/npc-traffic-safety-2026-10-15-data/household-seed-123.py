"""Reproduce the known household liveness gap independently of pytest RNG order.

Run from the repository: PYTHONPATH=src .venv/bin/python <this file>
Uses the real manager-loop test without replacing any driving decisions.
"""
import json
from pathlib import Path
import random
import runpy
import sys

root = Path(__file__).resolve().parents[3]
scenario = runpy.run_path(str(root / "tests/test_npc_population.py"))
random.seed(123)
try:
    scenario["test_household_vehicle_ownership_persists_through_a_full_trip_cycle"]()
except AssertionError as error:
    trace = error.__traceback__
    while trace.tb_next:
        trace = trace.tb_next
    state = trace.tb_frame.f_locals
    vehicle = state.get("vehicle")
    driver = state["manager"].drivers.get(vehicle.vehicle_id) if vehicle else None
    print(json.dumps({
        "seed": 123, "outcome": "failed", "assertion": str(error),
        "vehicle_state": vehicle.state if vehicle else None,
        "wait": vehicle.debug_waiting_for if vehicle else None,
        "pose": [vehicle.x, vehicle.y, vehicle.heading] if vehicle else None,
        "recovery": driver.recovery_stage if driver else None,
        "destination": driver.destination if driver else None,
        "path_index": driver.path_index if driver else None,
    }, indent=2))
    sys.exit(1)
print(json.dumps({"seed": 123, "outcome": "passed"}))
