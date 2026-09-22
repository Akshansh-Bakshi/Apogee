# Apogee

**A Temporal-Semantic Retrieval System for Personal Web Exploration.**

Apogee is a self-hosted personal web-memory system. The goal: you describe a page you half-remember
("that article about consensus algorithms I read on my phone last month") and Apogee finds it,
using semantic embeddings, temporal/session context, and a learned ranking model. Your data lives
in a backend and database that *you* run. Multiple devices will feed one user account. Privacy
controls are a first-class requirement, not an afterthought (see [docs/privacy.md](docs/privacy.md)).

## Current scope: Day 1 (backend foundation only)

This repository currently contains **only** the infrastructure the later ML and retrieval work will
sit on:

- FastAPI application with a single endpoint, `GET /api/v1/health`, which really queries PostgreSQL
- PostgreSQL + [pgvector](https://github.com/pgvector/pgvector), via Docker Compose
- SQLAlchemy 2.x models and an Alembic migration for `users`, `devices`, `pages`, `browsing_events`
- Environment-based configuration (no credentials in code)
- pytest suite (unit tests + tests against a real PostgreSQL)
- Documentation: this file, [docs/architecture.md](docs/architecture.md), [docs/privacy.md](docs/privacy.md)

### Not implemented yet

Browser extension and capture, privacy filtering, ingestion endpoints, authentication and device
sync, embeddings, semantic search / vector retrieval, temporal or session scoring, learned ranking,
clustering / drift analysis, and the dashboard. `extension/`, `dashboard/` and `ml/` contain only a
README marking the project boundary. See [docs/architecture.md](docs/architecture.md).

## Architecture at this stage

```
   (future)                      CURRENT
 Browser extension  ──►   FastAPI  ──►  PostgreSQL 16 + pgvector
                          /api/v1/health   users · devices · pages · browsing_events
```

Data model in one line: a **user** owns many **devices**; a device produces **browsing events**;
events point at one canonical **page** per (user, URL), so repeat visits do not duplicate pages.
Every table carries or inherits `user_id` with `ON DELETE CASCADE`. Details and trade-offs are in
[docs/architecture.md](docs/architecture.md).

## Prerequisites

- Docker with Compose v2 (`docker compose`), for the database and the containerised backend
- Optional, to run the API and tests directly on your machine: Python 3.12+

## Setup

All commands are run from the repository root.

```bash
# 1. Configuration. Set POSTGRES_PASSWORD (e.g. `openssl rand -hex 24`); .env is git-ignored.
cp .env.example .env

# 2. Start PostgreSQL (with pgvector) and the backend
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d
```

### Database setup and migrations

The pgvector extension is enabled by the first migration (`CREATE EXTENSION IF NOT EXISTS vector`).
Never change the schema by hand; write a migration.

```bash
# Apply all migrations to the (fresh) database
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm backend alembic upgrade head

# Inspect state / history
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm backend alembic current
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm backend alembic history

# Confirm the pgvector extension is installed (look for "vector" in the list)
docker compose --env-file .env -f infrastructure/docker-compose.yml exec db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dx"'

# Create a new migration after changing models (review the generated file before committing)
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm backend \
  alembic revision --autogenerate -m "describe the change"
```

### Start the API

`up -d` (above) already starts the API with auto-reload on <http://localhost:8000>. Interactive docs
are at <http://localhost:8000/docs>. Until migrations have been applied, `/api/v1/health` returns
`503` with status `degraded` (the database is reachable but pgvector is not enabled yet); after
`alembic upgrade head` it returns `200`. Logs: `docker compose --env-file .env -f infrastructure/docker-compose.yml logs -f backend`.

### Run the tests

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml run --rm backend pytest
```

The database tests create a throwaway database (`apogee_test_<random>`) on the same server, build it
with `alembic upgrade head`, and drop it afterwards. Your development database is never touched.
Tests that need no database can be run alone with `pytest -m "not db"`.

### Running without Docker for the backend

Start only the database (`... up -d db`), keep `POSTGRES_HOST=localhost` in `.env`, then:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:create_app --factory --reload
pytest
```

## Health endpoint

`GET /api/v1/health` opens a database connection, runs a query, and reports the PostgreSQL version
and whether the pgvector extension is installed.

| Situation | HTTP | `status` |
|---|---|---|
| Database reachable, pgvector installed | 200 | `ok` |
| Database reachable, pgvector missing (migrations not applied) | 503 | `degraded` |
| Database unreachable | 503 | `unavailable` |

Shape of a healthy response (values vary):

```json
{
  "status": "ok",
  "application": {"name": "Apogee", "version": "0.1.0", "environment": "development"},
  "database": {"status": "ok", "server_version": "16.x", "pgvector_version": "0.x.x",
               "latency_ms": 1.4, "detail": null}
}
```

Error responses deliberately omit hosts, usernames and SQL; the cause is logged server-side.

## Configuration

All settings are environment variables (see [.env.example](.env.example)). There are no default
credentials: the app refuses to start without `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD`.

## Repository layout

```
backend/        FastAPI app (app/), Alembic migrations (migrations/), tests (tests/)
infrastructure/ docker-compose.yml
docs/           architecture.md, privacy.md
extension/ dashboard/ ml/   future components (README only)
```
