# Dataset schema: `apogee-rerank-v1`

All files are UTF-8 JSON Lines, one JSON object per line. Input query rows are validated by
`QueryRecord` in `dataset.py`; output candidate rows are validated by `CandidateRecord`.
`queries.template.jsonl` and `annotation.template.jsonl` use conspicuous placeholder identifiers
and text. They are schema templates only: they do not describe a real user, query, page, history,
or annotation. Replace placeholder values before use.

## Query rows

| Field | Type | Meaning |
|---|---|---|
| `query_id` | UUID | Unique query row identifier |
| `task_group_id` | UUID | Shared by paraphrases of one underlying retrieval task |
| `user_id` | UUID | Existing Apogee user scope |
| `query_text` | non-empty string | Recollection query in the annotator's words |
| `query_timestamp` | timezone-aware ISO timestamp | Time at which features are evaluated |
| `target_page_id` | UUID or null | Genuine intended source, when known |
| `difficulty` | `easy`, `medium`, `hard` | Human-assigned task difficulty |
| `query_provenance` | enum | `manual_authored`, `generated_draft`, or `generated_human_reviewed` |
| `dataset_version` | string | Must equal `apogee-rerank-v1` |

The format cannot prove that a target is genuine. Those are collection and review responsibilities.
Use `generated_draft` for generated query text pending human review,
`generated_human_reviewed` only after human review, and `manual_authored` for manually authored
queries. Do not present generated text as observed user memory.

## Candidate rows

There is at most one row per `(query_id, candidate_page_id)`. Fields include identifiers and query
metadata; source presence flags; best chunk scores/ranks; chunk-hit counts; page-level RRF;
temporal features; labels and label provenance. No page title, URL, page text, or embedding vector
is exported. Semantic and lexical best scores may come from different chunks on the same page.
Ranks are 1-based positions in the endpoint's returned chunk list; for a page with multiple hits,
the saved rank belongs to its best-scoring chunk for that source. `semantic_chunk_hit_count` and
`lexical_chunk_hit_count` count hits within each returned list.

RRF is `sum(1 / (60 + page_rank))` across the available source ranks. `page_rank` is the best chunk
rank for that page in that source. Endpoints return at most 50 chunks; pages outside those
cutoffs cannot appear in the candidate union.

Temporal event fields only count rows owned by the query user and candidate page with
`occurred_at <= query_timestamp`. `recency_seconds` is relative to query time. The current Page
`last_seen_at` is deliberately excluded. `history_missing` means no eligible visit event was
available. Session count is null when there are events but no non-null session IDs (or no event
history); coverage is the fraction of eligible visit events with a session ID. `session_feature_missing`
flags no observed session IDs. This makes the feature explicit but does not make session modeling
useful when coverage is zero.

## Label states

`relevance_grade` is nullable and in `{0, 1, 2, 3}`: irrelevant, related but not useful, strongly
relevant alternative, correct source page. A retrieved `target_page_id` is initialized as grade 3
with `known_target`; this is only appropriate when the target is genuinely the intended source.
Other rows start with null grade and `review_required`. Do not infer that unreviewed rows are
irrelevant. Human-reviewed labels should use `independently_judged` and set `label_provenance` to a
review record or documented annotator key. Reviewers may edit the candidate JSONL; run validation
after annotation.

## Query status rows

`query_status.jsonl` records each query's semantic and lexical statuses (`ok`, `empty`, `failed`),
safe error category, chunk counts, merged page count, whether the target was retrieved, and history
feature status. `empty` means the endpoint returned HTTP success with zero hits. A failure never
becomes an empty observation. If history lookup fails, status is marked failed and no candidate rows
for that query are written because missing history cannot be distinguished safely from a database
failure.
