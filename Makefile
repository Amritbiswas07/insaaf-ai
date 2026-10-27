.PHONY: setup test lint api web up down

setup:            ## create venv + install backend and frontend
	cd backend && python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

test:             ## backend tests + frontend type-check
	cd backend && .venv/bin/pytest -q
	cd frontend && npm run typecheck

lint:
	cd backend && .venv/bin/ruff check src tests

api:              ## run the API with reload on :8000
	cd backend && .venv/bin/insaaf serve --reload

web:              ## run the frontend dev server on :5173
	cd frontend && npm run dev

up:               ## full stack in Docker
	docker compose up -d --build

down:
	docker compose down
