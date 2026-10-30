ENV ?= dev
PYTHON ?= python3

.PHONY: help bootstrap plan apply destroy status github clean-all test
help:
	@$(PYTHON) scripts/platform.py --help
bootstrap plan apply destroy status github clean-all:
	@$(PYTHON) scripts/platform.py $@ --env "$(ENV)"
test:
	@.venv/bin/python -m pytest -q
