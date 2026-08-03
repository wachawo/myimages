PYTHON ?= python3

.DEFAULT_GOAL := help
.PHONY: help install dev run lint format typecheck test check appimage deb

help:
	@echo "Targets: install dev run lint format typecheck test check appimage deb"

install:
	$(PYTHON) -m pip install -e .

dev:
	$(PYTHON) -m pip install -e ".[dev,trash,heif]"
	pre-commit install

run:
	$(PYTHON) main.py

lint:
	ruff check myimages tests

format:
	black myimages tests
	ruff check --fix myimages tests

typecheck:
	mypy myimages

test:
	pytest --cov=myimages --cov-report=term-missing --cov-fail-under=90

check: lint typecheck test

appimage:
	bash packaging/build_appimage.sh

deb:
	bash packaging/build_deb.sh
