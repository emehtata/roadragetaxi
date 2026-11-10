PYTHON := .venv/bin/python
PIP := .venv/bin/pip
WINDOWS_GODOT ?= C:\Godot\Godot_v$(GODOT_VERSION)-stable_win64_console.exe
WINDOWS_RTX_GODOT ?= C:\Godot\rtx\godot.windows.editor.x86_64.llvm.console.exe
RTX_QUALITY ?= native
GODOT_VERSION ?= 4.7.2
GODOT ?= $(HOME)/tools/godot/Godot_v$(GODOT_VERSION)-stable_linux.x86_64
PORT ?= 8765
PRESET ?= Oulu
BOT_MINUTES ?= 10
BOT_OUT ?= /tmp/rrt-play-bot

.PHONY: help venv install run run-2d run-rtx run-windows run-debug run-pbf index-pbf install-osmium run-server docker-build docker-run docker-start docker-stop docker-rm docker-rmi fetch-godot run-godot run-godot-all play-bot godot-selftest godot-selftest-sample godot-test audio-check test compile check clean stop

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'run                    Start the game with the 3D outdoor view (native Windows Godot under WSL)' \
		'run-2d                 Start the game with the 2D outdoor view' \
		'run-windows            Start native Windows Godot with its Windows Python server' \
		'run-rtx                Experimental NVIDIA path tracing (WINDOWS_RTX_GODOT, RTX_QUALITY=native|quality)' \
		'run-debug              Start the game with DEBUG logging' \
		'run-pbf                Start the game with the map from the local .osm.pbf extract' \
		'index-pbf              Build the grid index for the local .osm.pbf extract (faster run-pbf)' \
			'install-osmium         Install osmium-tool (needed for run-pbf): apt on Linux, Homebrew on macOS' \
		'run-server             Start the headless simulation server (PRESET=Oulu PORT=8765)' \
		'docker-build           Build the simulation server Docker image' \
		'docker-run             Build and start the simulation server container' \
		'docker-start           Start the existing simulation server container' \
		'docker-stop            Stop the simulation server container' \
		'docker-rm              Stop and remove the simulation server container' \
		'docker-rmi             Remove the simulation server image' \
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

ifneq ($(wildcard /proc/sys/fs/binfmt_misc/WSLInterop),)
run:
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$$(wslpath -w "$$PWD/tools/run-windows.ps1")" -Godot "$(WINDOWS_GODOT)" -Outdoor3d

run-2d: run-windows

run-debug:
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$$(wslpath -w "$$PWD/tools/run-windows.ps1")" -Godot "$(WINDOWS_GODOT)" -DebugLogging

run-pbf:
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$$(wslpath -w "$$PWD/tools/run-windows.ps1")" -Godot "$(WINDOWS_GODOT)" -LocalPbf
else
run: godot/.godot/import-stamp
	$(GODOT) --path godot -- --outdoor-3d

run-2d: godot/.godot/import-stamp
	$(GODOT) --path godot

run-debug: godot/.godot/import-stamp
	$(GODOT) --path godot -- --log-level DEBUG

run-pbf: godot/.godot/import-stamp
	$(GODOT) --path godot -- --osm-source pbf
endif

run-windows:
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$$(wslpath -w "$$PWD/tools/run-windows.ps1")" -Godot "$(WINDOWS_GODOT)"

run-rtx:
	powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$$(wslpath -w "$$PWD/tools/run-windows.ps1")" -Godot "$(WINDOWS_RTX_GODOT)" -ExperimentalRtx -RtxQuality "$(RTX_QUALITY)"

index-pbf:
	$(PYTHON) src/theroadragetrip/utils/pbf_index.py src/theroadragetrip/assets/osm/finland-latest.osm.pbf

install-osmium:
	@case "$$(uname -s)" in \
		Linux) sudo apt-get update && sudo apt-get install -y osmium-tool ;; \
		Darwin) brew install osmium-tool ;; \
		*) echo 'install-osmium: unsupported OS; install osmium-tool by hand' >&2; exit 1 ;; \
	esac

run-server:
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30

docker-build:
	docker compose -f docker/compose.yaml build

docker-run:
	docker compose -f docker/compose.yaml up --build -d

docker-start:
	docker compose -f docker/compose.yaml start

docker-stop:
	docker compose -f docker/compose.yaml stop

docker-rm:
	docker compose -f docker/compose.yaml down

docker-rmi:
	docker image rm docker-simulation-server

fetch-godot: $(GODOT)

$(GODOT):
	mkdir -p $(dir $@)
	curl -fL -o $@.zip https://github.com/godotengine/godot/releases/download/$(GODOT_VERSION)-stable/$(notdir $@).zip
	unzip -o -d $(dir $@) $@.zip && rm $@.zip && chmod +x $@

# A fresh checkout has no .godot/ class cache; import once or class_name types fail to parse.
# Re-import whenever an asset gained or changed an .import sidecar: a stale cache
# made the scripts that preload new models (e_scooter_grab3d.glb, mountain_bike.glb) fail to compile.
# Also re-import when a class_name script is added or changed: the class cache lacked
# the new Precipitation3D and buildings_3d.gd failed to parse.
IMPORT_SIDECARS := $(shell find godot -name "*.import" -not -path "godot/.godot/*" 2>/dev/null)
CLASS_SCRIPTS := $(shell grep -rl '^class_name' godot --include=*.gd --exclude-dir=.godot 2>/dev/null)

godot/.godot/import-stamp: $(IMPORT_SIDECARS) $(CLASS_SCRIPTS) | $(GODOT)
	$(GODOT) --headless --path godot --import
	touch $@

run-godot: godot/.godot/import-stamp
	$(GODOT) --path godot -- --skip-menu --port $(PORT)

play-bot: godot/.godot/import-stamp
	mkdir -p $(BOT_OUT)
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 --game-mode gig_driver > $(BOT_OUT)/server.log 2>&1 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 240 && $(GODOT) --path godot --script $(CURDIR)/tools/play_bot.gd -- \
		--skip-menu --port $(PORT) --bot-out $(BOT_OUT) --bot-minutes $(BOT_MINUTES) 2>&1 | tee $(BOT_OUT)/godot.log

run-godot-all: godot/.godot/import-stamp
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 180 && $(GODOT) --path godot -- --skip-menu --port $(PORT)

godot-selftest: godot/.godot/import-stamp
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --preset $(PRESET) --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 180 && \
	$(GODOT) --headless --path godot -- --port $(PORT) --selftest

godot-selftest-sample: godot/.godot/import-stamp
	PYTHONPATH=src $(PYTHON) -m theroadragetrip.server --use-sample --no-historical-weather --port $(PORT) --tick-rate 30 & \
	server=$$!; trap 'kill $$server' EXIT INT TERM; \
	$(PYTHON) tools/wait_for_port.py 127.0.0.1 $(PORT) 60 && \
	$(GODOT) --headless --path godot -- --port $(PORT) --selftest | tee /dev/stderr | grep -q 'SELFTEST {.*"ok":true'

godot-test:
	$(GODOT) --headless --path godot --import
	$(GODOT) --headless --path godot --script res://tests/run_tests.gd
	$(GODOT) --headless --path godot --script res://tests/audit_menu_safety.gd
	$(GODOT) --headless --path godot --script res://tests/home_interior.gd
	$(GODOT) --headless --path godot --script res://tests/electronic_signs.gd
	$(GODOT) --headless --path godot --script res://tests/surface_details.gd
	$(GODOT) --headless --path godot --script res://tests/forest_trees.gd
	$(GODOT) --headless --path godot --script res://tests/precipitation_3d.gd
	$(GODOT) --headless --path godot --script res://tests/animal_audio.gd
	$(GODOT) --headless --path godot --script res://tests/rtx_trial.gd
	$(GODOT) --headless --path godot --script res://tests/home_walk.gd
	$(GODOT) --headless --path godot --script res://tests/home_interior_3d.gd
	$(GODOT) --headless --path godot --script res://tests/home_first_person.gd
	$(GODOT) --headless --path godot --script res://animal_models_test.gd

audio-check:
	PYTHONPATH=src $(PYTHON) tools/validate_audio_assets.py

test:
	sh tools/check_class_cache.sh
	PYTHONPATH=src $(PYTHON) -m pytest -q -n auto -m "not timing"
	PYTHONPATH=src $(PYTHON) -m pytest -q -m timing

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
