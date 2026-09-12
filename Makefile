SHELL := /bin/bash

.PHONY: up down logs ps build config test test-unit test-security test-functionality test-mcp test-all

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

build:
	docker compose build

config:
	docker compose config

test: test-unit

test-unit:
	docker compose run --rm --no-deps gateway pytest -q tests

# Live tests assume the stack is already running.
test-security:
	./scripts/test-security.sh

test-functionality:
	./scripts/test-functionality.sh

test-mcp:
	./scripts/test-mcp.sh

test-all:
	./scripts/test-all.sh
