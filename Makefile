# Jarvis — developer ergonomics. Run from the repo root.
.DEFAULT_GOAL := help
COMPOSE := docker compose

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: token
token: ## Generate a random AUTH_SHARED_TOKEN
	@python3 -c "import secrets; print(secrets.token_urlsafe(32))"

.PHONY: secret-key
secret-key: ## Generate a Fernet SECRET_ENCRYPTION_KEY (encrypts OAuth tokens at rest)
	@python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

.PHONY: google-connect
google-connect: ## Print the Google OAuth consent URL (open it in a browser)
	@set -a; . ./.env; set +a; \
		curl -fsS -H "Authorization: Bearer $$AUTH_SHARED_TOKEN" \
		http://localhost:$${BIND_PORT:-8000}/integrations/google/connect

.PHONY: calendar-today
calendar-today: ## Fetch today's calendar via the API (uses AUTH_SHARED_TOKEN from .env)
	@set -a; . ./.env; set +a; \
		curl -fsS -H "Authorization: Bearer $$AUTH_SHARED_TOKEN" \
		http://localhost:$${BIND_PORT:-8000}/calendar/today && echo

.PHONY: up
up: ## Build + start brain and db (foreground)
	$(COMPOSE) up --build

.PHONY: upd
upd: ## Build + start brain and db (detached)
	$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop and remove containers (keeps the db volume)
	$(COMPOSE) down

.PHONY: logs
logs: ## Tail brain logs
	$(COMPOSE) logs -f brain

.PHONY: migrate
migrate: ## Run Alembic migrations to head (inside the brain container)
	$(COMPOSE) exec brain .venv/bin/alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back the last migration
	$(COMPOSE) exec brain .venv/bin/alembic downgrade -1

.PHONY: test
test: ## Run the smoke test suite (inside the brain container; db must be up)
	$(COMPOSE) exec brain .venv/bin/pytest -q

.PHONY: health
health: ## Curl /health locally using AUTH_SHARED_TOKEN from .env
	@set -a; . ./.env; set +a; \
		curl -fsS -H "Authorization: Bearer $$AUTH_SHARED_TOKEN" \
		http://localhost:$${BIND_PORT:-8000}/health && echo

.PHONY: lint
lint: ## Lint the brain code
	$(COMPOSE) exec brain .venv/bin/ruff check app tests

.PHONY: fmt
fmt: ## Format the brain code
	$(COMPOSE) exec brain .venv/bin/ruff format app tests
