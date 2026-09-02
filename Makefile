PYTHON := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: help venv install run run-debug run-sample audit-ai test compile check clean

help:
	@printf '%s\n' \
		'install                Create .venv and install project dependencies' \
		'run                    Start the game' \
		'run-debug              Start the game with DEBUG logging' \
		'run-sample             Start offline with bundled sample data' \
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
