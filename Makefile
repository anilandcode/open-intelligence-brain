.PHONY: install dev-api dev-web test lint build

install:
	python3 -m venv .venv
	.venv/bin/pip install -e './api[dev]'
	npm --prefix web install

dev-api:
	.venv/bin/uvicorn brain.main:app --app-dir api --reload --port 8000

dev-web:
	npm --prefix web run dev

test:
	.venv/bin/pytest api/tests
	npm --prefix web run test

lint:
	.venv/bin/ruff check api
	npm --prefix web run lint

build:
	npm --prefix web run build

