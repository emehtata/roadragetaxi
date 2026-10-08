PYTHON := .venv/bin/python
PIP := .venv/bin/pip
GODOT_VERSION ?= 4.7.2
GODOT ?= $(HOME)/tools/godot/Godot_v$(GODOT_VERSION)-stable_linux.x86_64
PORT ?= 8765
PRESET ?= Oulu

.PHONY: help venv install run run-debug run-sample run-pbf index-pbf run-server fetch-godot run-godot run-godot-all run-godot-pbf godot-selftest godot-test audio-check audit-ai test compile check clean

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'run                    Start the game' \
		'run-debug              Start the game with DEBUG logging' \
		'run-sample             Start offline with bundled sample data' \
		'run-pbf                Start using the local .osm.pbf extract instead of Overpass' \
		'run-godot-pbf          Server from the local .osm.pbf extract + the Godot client' \
		'index-pbf              Build the grid index for the local .osm.pbf extract (faster run-pbf)' \
		'run-server             Start the headless simulation server (PRESET=Oulu PORT=8765)' \
		'fetch-godot            Download the Godot editor binary to $$(GODOT) if missing' \
		'run-godot              Start the Godot client against a running server (GODOT=path)' \
		'run-godot-all          Start the server in the background, then the Godot client' \
		'godot-selftest         Server + headless Godot selftest, prints a JSON report' \
		'godot-test             Run the Godot client unit tests (no server needed)' \
		'audio-check            Validate the sound catalog, files and every reference to them' \
		'audit-ai               Run headless autonomous traffic audit' \
		'test                   Run the test suite' \
		'compile                Compile-check Python sources' \
		'check                  Run tests, compile-check, and diff-check' \
		'clean                  Remove generated Python/test cache files'

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -r requirements.txt

run: godot/.godot
	$(GODOT) --path godot

run-debug: godot/.godot
	$(GODOT) --path godot -- --log-level DEBUG

run-sample:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --use-sample

run-pbf:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --osm-source pbf

index-pbf:
	$(PYTHON) src/theroadragetrip/utils/pbf_index.py src/theroadragetrip/assets/osm/finland-latest.osm.pbf

run-server:
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30

fetch-godot: $(GODOT)

$(GODOT):
	mkdir -p $(dir $@)
	curl -fL -o $@.zip https://github.com/godotengine/godot/releases/download/$(GODOT_VERSION)-stable/$(notdir $@).zip
	unzip -o -d $(dir $@) $@.zip && rm $@.zip && chmod +x $@

# A fresh checkout has no .godot/ class cache; import once or class_name types fail to parse.
godot/.godot: | $(GODOT)
	$(GODOT) --headless --path godot --import

run-godot: godot/.godot
	$(GODOT) --path godot -- --skip-menu --port $(PORT)

run-godot-all: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	sleep 5; $(GODOT) --path godot -- --skip-menu --port $(PORT)

run-godot-pbf: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 --osm-source pbf & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	sleep 5; $(GODOT) --path godot -- --skip-menu --port $(PORT)

godot-selftest: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	sleep 5; $(GODOT) --headless --path godot -- --port $(PORT) --selftest

godot-test:
	$(GODOT) --headless --path godot --import
	$(GODOT) --headless --path godot --script res://tests/run_tests.gd

audio-check:
	SDL_AUDIODRIVER=dummy PYTHONPATH=src $(PYTHON) tools/validate_audio_assets.py

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
