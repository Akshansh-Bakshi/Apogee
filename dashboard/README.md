# dashboard/

The local search dashboard is served by FastAPI at `http://127.0.0.1:8000/app`. Its files live
in `backend/app/ui/`; there is no separate frontend build or service.

Start the existing stack from the repository root:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml up -d --no-build
```

Open `http://127.0.0.1:8000/app`. Paste the existing development user UUID into the
**Local development user ID** field, enter a query, and choose Semantic or Lexical. The UUID is
held in this browser tab's session storage for convenience. It identifies which records the
existing API searches; it is **not authentication**. The Compose configuration binds the API
and database to `127.0.0.1`; keep it that way.

The dashboard asks the existing endpoints for up to 50 ranked chunks, then shows each page
once in the order of its best-ranked chunk. The preview comes from that chunk. A page with
many matching chunks can occupy several of the 50 positions, limiting page diversity. The
dashboard does not provide a live hybrid ranking; the ML evaluation's hybrid baseline is offline.

The **Exploration** section on the same page uses the development user ID above. Click
**Explore topics** to see provisional assignments summarized as distinct captured pages,
recorded visits, latest activity, related-topic breadth, and a browsing activity index.
Next-topic suggestions use only the fixed prerequisite graph and actual captured-page
evidence. They do not measure learning or mastery. The exact formula and sparse-evidence
rule are in `backend/app/services/TOPICS.md`.

The **Recorded browsing history** section is a bounded, read-only view of stored browsing
events. Click **Load timeline** to show at most 100 events, grouped by calendar date in the
browser's displayed IANA timezone. The optional dates are interpreted as local calendar
dates: **From** is inclusive and **Through** includes that whole day by sending the following
local midnight as an exclusive boundary. A topic filter uses the same provisional zero-shot
assignments as Exploration and scans at most 500 recent events. A truncation notice means the
date range should be narrowed. These rows are recorded visits; they are not inferred sessions,
learning progress, or authentication evidence.

The corresponding local-only endpoint is:

```text
GET /api/v1/history?user_id=<UUID>&start_at=<aware-ISO-8601>&end_at=<aware-ISO-8601>&topic_id=<taxonomy-id>&limit=50
```

`start_at` is inclusive, `end_at` is exclusive, and `limit` must be between 1 and 100. Results
are ordered by `occurred_at` descending and then event UUID descending. The response reports
whether its bounded scan was truncated and labels all topics as provisional cosine-similarity
suggestions. As elsewhere in the local app, `user_id` only scopes data and is not authentication.

Run dashboard checks without the development database:

```bash
docker compose --env-file .env -f infrastructure/docker-compose.yml exec backend pytest -m "not db"
node --test backend/tests/dashboard_results.test.mjs
node --test backend/tests/dashboard_exploration.test.mjs
node --test backend/tests/dashboard_history.test.mjs
```
