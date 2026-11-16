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

The dashboard uses `POST /api/v1/search/pages` with `user_id`, `query`, `mode` (semantic or
lexical), and `limit` (1–50 distinct pages). SQL selects each page's strongest chunk before
applying the page limit. Its preview and unchanged score are returned using the existing chunk
result fields. `result_unit: page` and `truncated` identify the new response semantics. One
look-ahead page determines truncation. The dashboard requests ten ranked pages initially and uses
the bounded `offset` field to fetch more only when requested, up to the first 50 pages. No extra
chunk evidence is returned, keeping the response
bounded. The original `/api/v1/search` and `/api/v1/search/lexical` remain chunk APIs for existing
clients and offline evaluation. The dashboard does not provide hybrid ranking.

Semantic pages sort by minimum cosine distance, then page UUID; equal chunks within a page use
chunk index and UUID. The old semantic endpoint has no defined tie-breaker, so exact-score ties
can differ while unequal scores retain their order. Lexical pages preserve descending rank,
descending last-seen time, page UUID, chunk index, and chunk UUID. The page query scores all
eligible user/model chunks (or lexical matches) in one database query and encodes a semantic
query once. This exact window operation does not benefit from the HNSW top-K shortcut and can
cost more as the archive grows. More distinct pages does not establish greater relevance.
Returned pages are labelled **possible matches**: lexical term matches and semantic nearest
neighbors do not independently establish relevance. Both search APIs add a backward-compatible
`result_state` field while retaining their ranked chunk lists and scores. Semantic search has no
calibrated relevance cutoff and can return weak neighbors even for unrelated queries. Lexical
search uses PostgreSQL English stemming and AND semantics for ordinary multiword queries;
matching all stems can still be incidental. Empty results do not prove that a topic was never
visited. The dashboard retains defensive page grouping for compatibility; the new API already
returns unique pages. These messages were chosen from a small development diagnostic, not a
held-out test.

The **Exploration** section on the same page uses the development user ID above. Click
**Explore topics** to see provisional assignments summarized as distinct captured pages,
recorded visits, latest activity, related-topic breadth, and a browsing activity index.
The Exploration Graph shows all eight frozen topics and the three explicit prerequisite arrows.
Node size reflects directly assigned captured pages. Select nodes by pointer, Enter, Space or
the accessible list for evidence details; zoom with the wheel, drag to pan, or reset the view.
The model's top three topics use overall captured browsing history, independent of the search
query, and show expected synthetic rubric grades. The separate prerequisite suggestions follow
the fixed graph and sparse captured-page evidence. A zero-page topic may have a nonzero activity
index from related-topic breadth. Neither index nor model grade measures learning mastery,
confidence or verified usefulness. The exact activity formula and graph rule are in
[`backend/app/services/TOPICS.md`](../backend/app/services/TOPICS.md); model provenance is in
[`docs/next-topic-model.md`](../docs/next-topic-model.md).

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
node --test backend/tests/dashboard_graph.test.mjs
```
