PYTHON := .venv/bin/python
PIP := .venv/bin/pip
GODOT ?= $(HOME)/tools/godot/Godot_v4.7.2-stable_linux.x86_64
PORT ?= 8765
PRESET ?= Oulu

.PHONY: help venv install run run-debug run-sample run-pbf index-pbf run-server run-godot run-godot-all godot-selftest godot-test audit-ai test compile check clean

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'run                    Start the game' \
		'run-debug              Start the game with DEBUG logging' \
		'run-sample             Start offline with bundled sample data' \
		'run-pbf                Start using the local .osm.pbf extract instead of Overpass' \
		'index-pbf              Build the grid index for the local .osm.pbf extract (faster run-pbf)' \
		'run-server             Start the headless simulation server (PRESET=Oulu PORT=8765)' \
		'run-godot              Start the Godot client against a running server (GODOT=path)' \
		'run-godot-all          Start the server in the background, then the Godot client' \
		'godot-selftest         Server + headless Godot selftest, prints a JSON report' \
		'godot-test             Run the Godot client unit tests (no server needed)' \
		'audit-ai               Run headless autonomous traffic audit' \
		'test                   Run the test suite' \
		'compile                Compile-check Python sources' \
		'check                  Run tests, compile-check, and diff-check' \
		'clean                  Remove generated Python/test cache files'

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -r requirements.txt

run:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py

run-debug:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --log-level DEBUG

run-sample:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --use-sample

run-pbf:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --osm-source pbf

index-pbf:
	$(PYTHON) src/theroadragetrip/utils/pbf_index.py src/theroadragetrip/assets/osm/finland-latest.osm.pbf

run-server:
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30

run-godot:
	$(GODOT) --path godot -- --port $(PORT)

run-godot-all:
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	sleep 5; $(GODOT) --path godot -- --port $(PORT)

godot-selftest:
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	sleep 5; $(GODOT) --headless --path godot -- --port $(PORT) --selftest

godot-test:
	$(GODOT) --headless --path godot --import
	$(GODOT) --headless --path godot --script res://tests/run_tests.gd

audit-ai:
	PYTHONPATH=src $(PYTHON) utils/autoplay_audit.py

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

compile:
	$(PYTHON) -m compileall -q src/theroadragetrip

check: test compile
	git diff --check

clean:
	find . -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
