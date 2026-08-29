PYTHON := .venv/bin/python
PIP := .venv/bin/pip
VOICE_DIR ?= $(HOME)/.local/share/RoadRageTrip/voices
PIPER_VOICES := fi_FI-harri-medium en_US-lessac-medium

.PHONY: help venv install install-speech-models run run-sample test compile check clean

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'install-speech-models Install Piper and Finnish/English voice models' \
		'run                    Start the game' \
		'run-sample             Start offline with bundled sample data' \
		'test                   Run the test suite' \
		'compile                Compile-check Python sources' \
		'check                  Run tests, compile-check, and diff-check' \
		'clean                  Remove generated Python/test cache files'

venv:
	python3 -m venv .venv

install: venv
	$(PIP) install -r requirements.txt

install-speech-models: install
	mkdir -p "$(VOICE_DIR)"
	$(PYTHON) -m piper.download_voices --download-dir "$(VOICE_DIR)" $(PIPER_VOICES)

run:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py

run-sample:
	PYTHONPATH=src $(PYTHON) road_rage_trip.py --use-sample

test:
	PYTHONPATH=src $(PYTHON) -m pytest -q

compile:
	$(PYTHON) -m compileall -q src/theroadragetrip

check: test compile
	git diff --check

clean:
	find . -type d \( -name '__pycache__' -o -name '.pytest_cache' \) -prune -exec rm -rf {} +
