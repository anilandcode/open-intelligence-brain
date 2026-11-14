.PHONY: install dev-api dev-web test lint build

install:
	python3 -m venv .venv
	.venv/bin/pip install -e './api[dev,identity]'
	.venv/bin/pip install -e sdks/python
	npm --prefix web install
	npm --prefix sdks/typescript install

dev-api:
	.venv/bin/uvicorn brain.main:app --app-dir api --reload --port 8000

dev-web:
	npm --prefix web run dev

test:
	.venv/bin/pytest api/tests
	.venv/bin/python benchmarks/run_provenance_benchmark.py
	npm --prefix web run test
	npm --prefix sdks/typescript test

lint:
	.venv/bin/ruff check api sdks/python benchmarks
	.venv/bin/ruff format --check api sdks/python benchmarks
	npm --prefix web run lint

build:
	npm --prefix sdks/typescript run build
	npm --prefix web run build

