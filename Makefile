# SPDX-FileCopyrightText: 2026 Vitor Mattos <vitor@php.rio>
#
# SPDX-License-Identifier: AGPL-3.0-or-later

.PHONY: test lint build up down logs plugin

test:
	python -m pytest -q

lint:
	ruff check src tests scripts

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f mcp tunnel-client

plugin:
	python scripts/build_plugin.py
