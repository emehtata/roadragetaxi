PYTHON := .venv/bin/python
PIP := .venv/bin/pip
GODOT_VERSION ?= 4.7.2
GODOT ?= $(HOME)/tools/godot/Godot_v$(GODOT_VERSION)-stable_linux.x86_64
PORT ?= 8765
PRESET ?= Oulu
BOT_MINUTES ?= 10
BOT_OUT ?= /tmp/rrt-play-bot

.PHONY: help venv install run run-debug run-pbf index-pbf run-server fetch-godot run-godot run-godot-all play-bot godot-selftest godot-selftest-sample godot-test audio-check test compile check clean stop

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'run                    Start the game' \
		'run-debug              Start the game with DEBUG logging' \
		'run-pbf                Start the game with the map from the local .osm.pbf extract' \
		'index-pbf              Build the grid index for the local .osm.pbf extract (faster run-pbf)' \
		'run-server             Start the headless simulation server (PRESET=Oulu PORT=8765)' \
		'fetch-godot            Download the Godot editor binary to $$(GODOT) if missing' \
		'run-godot              Start the Godot client against a running server (GODOT=path)' \
		'run-godot-all          Start the server in the background, then the Godot client' \
		'play-bot               Play-test: tools/play_bot.gd drives the Godot client (BOT_MINUTES, BOT_OUT)' \
		'godot-selftest         Server + headless Godot selftest, prints a JSON report' \
		'godot-selftest-sample  The same on the bundled sample map: offline, fails unless ok' \
		'godot-test             Run the Godot client unit tests (no server needed)' \
		'audio-check            Validate the sound catalog, files and every reference to them' \
		'test                   Run the test suite' \
		'compile                Compile-check Python sources' \
		'check                  Run tests, compile-check, and diff-check' \
		'clean                  Remove generated Python/test cache files' \
		'stop                   Kill every game instance: Godot clients, servers and their map-build workers'

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -r requirements.txt

run: godot/.godot
	$(GODOT) --path godot

run-debug: godot/.godot
	$(GODOT) --path godot -- --log-level DEBUG

run-pbf: godot/.godot
	$(GODOT) --path godot -- --osm-source pbf

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

play-bot: godot/.godot
	mkdir -p $(BOT_OUT)
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 --game-mode gig_driver > $(BOT_OUT)/server.log 2>&1 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 240 && $(GODOT) --path godot --script $(CURDIR)/tools/play_bot.gd -- \
		--skip-menu --port $(PORT) --bot-out $(BOT_OUT) --bot-minutes $(BOT_MINUTES) 2>&1 | tee $(BOT_OUT)/godot.log

run-godot-all: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 180 && $(GODOT) --path godot -- --skip-menu --port $(PORT)

godot-selftest: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 180 && \
	$(GODOT) --headless --path godot -- --port $(PORT) --selftest

godot-selftest-sample: godot/.godot
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --use-sample --no-historical-weather --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 60 && \
	$(GODOT) --headless --path godot -- --port $(PORT) --selftest | tee /dev/stderr | grep -q 'SELFTEST {.*"ok":true'

godot-test:
	$(GODOT) --headless --path godot --import
	$(GODOT) --headless --path godot --script res://tests/run_tests.gd
	$(GODOT) --headless --path godot --script res://tests/animal_audio.gd

audio-check:
	PYTHONPATH=src $(PYTHON) tools/validate_audio_assets.py

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

compile:
	$(PYTHON) -m compileall -q src/theroadragetrip

check: test compile
	git diff --check

clean:
	find . -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +

stop:
	-pkill -f -- '--path [g]odot'
	-pkill -f -- '-m [t]heroadragetrip\.server'
	-pkill -f -- '$(CURDIR)/\.venv/bin/python -c [f]rom multiprocessing\.spawn'  # not the resource tracker: it cleans up after the rest
