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
	docker compose logs -f mcp

plugin:
	python scripts/build_plugin.py --url "${MCP_PUBLIC_URL}/mcp"
