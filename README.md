# Apogee

**A Temporal-Semantic Retrieval System for Personal Web Exploration.**

Apogee is a self-hosted personal web-memory system. The goal: you describe a page you half-remember
("that article about consensus algorithms I read on my phone last month") and Apogee finds it,
using semantic embeddings, temporal/session context, and a learned ranking model. Your data lives
in a backend and database that *you* run. Multiple devices will feed one user account. Privacy
controls are a first-class requirement, not an afterthought (see [docs/privacy.md](docs/privacy.md)).

## Current scope: Days 1-2 (backend foundation + first ingestion layer)

This repository contains the infrastructure the later ML and retrieval work sits on, and the first
reliable path for data to get into it:

- FastAPI application: `GET /api/v1/health` (really queries PostgreSQL) and
  `POST /api/v1/capture` (records one browsing event; see [Ingestion flow](#ingestion-flow))
- Pure, conservative URL normalisation and hostname extraction (`app/core/urls.py`)
- Page upsert + event insert in one transaction, using PostgreSQL's `ON CONFLICT`
- PostgreSQL + [pgvector](https://github.com/pgvector/pgvector), via Docker Compose
- SQLAlchemy 2.x models and an Alembic migration for `users`, `devices`, `pages`, `browsing_events`
- Environment-based configuration (no credentials in code)
- pytest suite (pure unit tests + tests against a real PostgreSQL)
- Documentation: this file, [docs/architecture.md](docs/architecture.md), [docs/privacy.md](docs/privacy.md)

### Not implemented yet

Browser extension and capture, client-side privacy filtering and exclusion management, **authentication
and device registration/sync** (the capture endpoint is an unauthenticated development-stage boundary),
page content/text extraction, embeddings, semantic search / vector retrieval, temporal or session
scoring, learned ranking, clustering / drift analysis, and the dashboard. `extension/`, `dashboard/`
and `ml/` contain only a README marking the project boundary. See
[docs/architecture.md](docs/architecture.md).

## Architecture at this stage

```
   (future)                      CURRENT
 Browser extension  ──►   FastAPI  ──►  PostgreSQL 16 + pgvector
                          /api/v1/capture   users · devices · pages · browsing_events
                          /api/v1/health
```

Data model in one line: a **user** owns many **devices**; a device produces **browsing events**;
events point at one canonical **page** per (user, canonical URL), so repeat visits do not duplicate pages.
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
Tests that need no database can be run alone with `pytest -m "not db"` (this includes the URL
normalisation, request-validation, and error-handling tests).

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

## Ingestion flow

```
Browser event
     ↓
POST /api/v1/capture
     ↓
validation            Pydantic: UUIDs, timestamp, title length, URL acceptable; unknown fields rejected
     ↓
URL normalisation     → canonical URL + hostname (pure functions, no network)
     ↓
page upsert           INSERT … ON CONFLICT (user_id, canonical_url) DO UPDATE   (PostgreSQL enforces uniqueness)
     ↓
browsing event        always a new row, pointing at the page
     ↓
COMMIT                page and event are written atomically, or neither is
```

A repeated visit to the same logical page reuses its `pages` row and adds a new `browsing_events`
row. These two visits resolve to one page (`https://example.com/tutorial?id=42`) and two events:

```
https://example.com/tutorial?id=42&utm_source=google#section1
https://example.com/tutorial?id=42&utm_source=twitter#section2
```

> **Development-stage boundary: this endpoint is NOT authenticated.** The caller supplies `user_id`
> and `device_id` and nothing verifies who they are, so anyone who can reach the port can write
> events for any user. Run it only on a trusted machine/network (the compose file binds to
> `127.0.0.1`). Authentication is deliberately deferred; see [docs/architecture.md](docs/architecture.md).
> Client-side privacy filtering (the future extension) must happen *before* upload; the server-side
> checks here are defence in depth. See [docs/privacy.md](docs/privacy.md).

### Try it

There is no user/device registration yet, so create a development user and device directly:

```bash
# prints a user id
docker compose --env-file .env -f infrastructure/docker-compose.yml exec -T db \
  sh -c 'psql -q -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "INSERT INTO users DEFAULT VALUES RETURNING id"'

# prints a device id (replace <USER_ID>)
docker compose --env-file .env -f infrastructure/docker-compose.yml exec -T db \
  sh -c 'psql -q -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "INSERT INTO devices (user_id, label) VALUES ('"'"'<USER_ID>'"'"', '"'"'dev laptop'"'"') RETURNING id"'

curl -sS -X POST http://localhost:8000/api/v1/capture -H 'Content-Type: application/json' -d '{
  "user_id": "<USER_ID>",
  "device_id": "<DEVICE_ID>",
  "url": "https://example.com/tutorial?id=42&utm_source=google#section1",
  "title": "A tutorial",
  "occurred_at": "2026-01-01T12:00:00Z"
}'
```

### Request

| Field | Type | Notes |
|---|---|---|
| `user_id` | UUID | required |
| `device_id` | UUID | required; must belong to `user_id` |
| `url` | string | required; `http`/`https` only; no embedded credentials; up to 8192 characters raw (2048 once normalised) |
| `title` | string \| null | optional; up to 1024 characters; whitespace is collapsed, blank means no title |
| `occurred_at` | ISO-8601 timestamp | required; must include a timezone; not before 2000-01-01, not more than 5 minutes in the future |
| `session_id` | UUID \| null | optional client-assigned session identifier |

**No other fields are accepted.** Cookies, passwords, tokens, form values, browser storage, page
text, or anything else unknown is a `422`, not silently ignored.

### Response: `201 Created`

Every accepted request creates an event, so the status is always `201`; `page_created` says whether
the page is new.

```json
{
  "event_id": "…", "page_id": "…", "page_created": true,
  "canonical_url": "https://example.com/tutorial?id=42", "domain": "example.com",
  "title": "A tutorial",
  "first_seen_at": "2026-01-01T12:00:00Z", "last_seen_at": "2026-01-01T12:00:00Z",
  "occurred_at": "2026-01-01T12:00:00Z"
}
```

The stored URL is the normalised one; the raw URL (fragment, tracking parameters) is never persisted.

### Errors

All errors use one envelope: `{"error": {"code": "...", "message": "...", "details": [...]}}`. They never
contain SQL, connection details, stack traces, or the request's contents.

| Status | `code` | When |
|---|---|---|
| 422 | `validation_error` | malformed/unsupported URL, bad UUID or timestamp, oversized title, unknown field, invalid JSON |
| 404 | `device_not_found` | the device does not exist for that user (unknown user, unknown device, or someone else's) |
| 409 | `conflict` | the database rejected the write (rare race); safe to retry |
| 503 | `database_unavailable` | PostgreSQL unreachable; retry later |
| 500 | `internal_error` | anything unexpected |

Note: there is no client-side event id yet, so a client that retries after a timeout can create a
duplicate event. De-duplication is future work.

## Configuration

All settings are environment variables (see [.env.example](.env.example)). There are no default
credentials: the app refuses to start without `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD`.

## Repository layout

```
backend/        FastAPI app, Alembic migrations, tests
  app/api/        HTTP layer: routers (v1/health, v1/capture), dependencies, error handling
  app/schemas/    request/response contracts (Pydantic), separate from ORM models
  app/services/   ingestion: the transaction that normalises, upserts the page, inserts the event
  app/core/       configuration and pure utilities (URL normalisation)
  app/db/  app/models/   engine/session, ORM models
infrastructure/ docker-compose.yml
docs/           architecture.md, privacy.md
extension/ dashboard/ ml/   future components (README only)
```
