.PHONY: help setup setup-api setup-frontend up down restart build build-frontend rebuild-frontend logs ps dev-api dev-frontend

API_HOST ?= 0.0.0.0
API_PORT ?= 8000
FE_HOST ?= 0.0.0.0
FE_PORT ?= 3000
FE_API_URL ?= http://127.0.0.1:8000
FE_ASSISTANT_ID ?= agent

help:
	@echo "Available commands:"
	@echo "  make setup             Install backend + frontend dependencies"
	@echo "  make up                Build and start all services with Docker Compose"
	@echo "  make down              Stop all services"
	@echo "  make restart           Recreate and start all services"
	@echo "  make build             Build all images"
	@echo "  make build-frontend    Build frontend image only"
	@echo "  make rebuild-frontend  Rebuild frontend image and recreate container"
	@echo "  make logs              Tail all Docker Compose logs"
	@echo "  make ps                Show Docker Compose service status"
	@echo "  make dev-api           Run backend locally"
	@echo "  make dev-frontend      Run frontend locally (proxying backend)"

setup: setup-api setup-frontend

setup-api:
	pip install -r requirements.txt

setup-frontend:
	npm --prefix frontend install

up:
	docker compose up -d --build

down:
	docker compose down

restart: down up

build:
	docker compose build

build-frontend:
	docker compose build frontend

rebuild-frontend:
	docker compose build frontend
	docker compose up -d --no-deps --force-recreate frontend

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

dev-api:
	uvicorn src.app.main:app --host $(API_HOST) --port $(API_PORT) --reload

dev-frontend:
	NEXT_PUBLIC_API_URL=$(FE_API_URL) NEXT_PUBLIC_ASSISTANT_ID=$(FE_ASSISTANT_ID) npm --prefix frontend run dev -- --hostname $(FE_HOST) --port $(FE_PORT)
