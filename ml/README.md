# Apogee offline dataset preparation

This directory contains the offline, pre-training pipeline for query-to-page reranking. It calls
the existing semantic and lexical API endpoints, merges their chunk hits by page, and derives
history features from `BrowsingEvent` rows as of each query timestamp. It does not train a model or
change the API/database schema.

## Query input

The versioned Pydantic contract is `QueryRecord` in `dataset.py`. A JSONL file contains one query
record per line. `queries.template.jsonl` is a schema-only placeholder; replace its IDs, query text,
and provenance with real, approved annotation tasks. Queries should describe remembered content in
the annotator's words, not copy the target page title. Do not describe generated text as observed
human memory. Current accepted provenance values are `manual_authored`, `generated_draft`, and
`generated_human_reviewed`. Use `generated_draft` for generated queries awaiting review.

`target_page_id` may be null. Set it only when the query genuinely refers to that source page. If
that target is retrieved, its candidate is initialized at relevance grade 3 with
`label_status=known_target`. Other candidates have a null grade and `label_status=review_required`;
they are not presumed irrelevant. Reviewers may edit grades and provenance in the candidate JSONL.

## Generate and validate

Start the existing API and database using the repository instructions, apply migrations only if
the local database has not already been set up, then create a private JSONL input under
`ml/local-data/`. From the repository root, run:

```powershell
python -m ml.prepare_dataset --queries ml/local-data/queries.jsonl --output-dir ml/local-data/export
python -m ml.prepare_dataset --validate ml/local-data/export/candidates.jsonl
```

The generator reads database connection settings through `backend/app/core/config.py`; credentials
are not command-line arguments and are never printed. It calls `http://127.0.0.1:8000` by default;
`--api-base-url` can override that address. API result limits default to 50, matching the existing
endpoint maximum.

Outputs are deterministic JSONL: `candidates.jsonl` (one row per query-page candidate) and
`query_status.jsonl` (one row per query, including per-endpoint status, result counts, and safe
failure descriptions). Successful zero-result retrieval is represented as `empty`; endpoint,
network, parse, and database-feature errors are represented as failures, not empty observations.
If one retriever fails, results from the other are retained and the failure remains in query status.
No candidate rows are fabricated. Endpoint cutoffs can omit a page whose relevant chunk did not
make the top 50 chunk hits.

Features include best chunk similarity/rank, best lexical score/rank, source-presence flags,
source chunk-hit counts, and reciprocal-rank fusion using the first page rank from each source
(`k=60`). Temporal values use only this user's events with `occurred_at <= query_timestamp`; the
page's current `last_seen_at` is not used. Missing history is explicit. Session count is null when
no non-null session IDs are present; coverage is reported separately. Session features are not
operational in the currently reported local dataset, which has zero non-null session IDs.

## Label scheme

`relevance_grade` is nullable and ordinal:

| Grade | Meaning |
|---:|---|
| 0 | Irrelevant |
| 1 | Related but not useful |
| 2 | Strongly relevant alternative |
| 3 | Correct source page |

`label_status` is `known_target`, `review_required`, or `independently_judged`. Only genuine known
targets are initialized automatically. This pipeline does not independently judge candidates.

Keep personal queries and exports under `ml/local-data/`; that directory is ignored by Git. Review
`git status` before sharing or committing. No training labels or actual browsing content belong in
version control without explicit approval.

## Tests

From the repository root:

```powershell
python -m pytest ml/tests
```

The tests use mocked endpoint payloads and in-memory history fixtures; they do not depend on the
current local database or make API calls.
