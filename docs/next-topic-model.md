# Local synthetic next-topic model endpoint

`GET http://127.0.0.1:8000/api/v1/topics/recommendations/model?user_id=<UUID>` is read-only.
The caller-supplied UUID filters records and is not authentication. Keep Compose loopback bindings.
The dashboard shows an eight-topic Exploration Graph with exactly three directed prerequisite
edges, model top-three suggestions and a separate rule-based prerequisite section. Model ranking
uses overall captured browsing history, independent of the current search query.

The response contains `source` (`model` or `rule_based`), `fallback_reason`, `as_of`, versions,
provenance, assigned/unclassified page counts, eligible event count, `ranking`, and
`rule_recommendations` in the existing rule schema. `ranking` scores all eight frozen taxonomy
topics by expected synthetic grade P(1)+2P(2), with topic-ID tie breaking. Every item contains its
rank, topic ID, raw feature evidence and an explanation of observed counts and prerequisite
relationships. Explanations are descriptive evidence, not learned importance or causal attribution.

Feature order and formulas are shared with offline generation in `next_topic_features.py`.
The model uses topic ID, independent page/visit counts, nullable recency, observed-topic flag and
breadth, total counts, capped repeat ratio, page/visit shares, prerequisite counts/category, gap
flag and extension flag. Null recency means no eligible event; zero denominators yield zero shares.
Prerequisite evidence is captured-page evidence only. There is no mastery or inferred session input.

For each request, owned pages are selected, current Stage A assignments are calculated for those
pages using its cached encoder, and UTC `as_of` is recorded. Only owned events with occurrence
AND creation timestamps at or before `as_of` are read. The shared temporal adapter checks ownership
again. Page availability comes from Page.created_at; assignment availability is the current
observation time. Pages without embeddings remain unclassified. Events for unclassified or absent
pages cannot contribute to topic feature counts. Events are counted independently from pages.
There is no historical cutoff parameter. Current assignments cannot reconstruct past assignments.

No assigned pages produces `insufficient_observation_evidence`, including unknown users and an
empty corpus. Artifact failure reasons include `artifact_missing`, `artifact_untrusted`,
`runtime_mismatch`, `schema_mismatch`, `artifact_invalid`, and `prediction_invalid`. Fallback
returns an empty model ranking and graph recommendations, which may also be empty. Pages with
no eligible events remain usable page evidence with null recency. Invalid/future event timestamps
cannot enter recency (database timestamps are required; future times are filtered).

Limitations: the data comprise numbered batches from one synthetic generator with rule labels
and synthetic label noise. There is no real recommendation feedback. The live corpus may lie
outside synthetic training ranges. All eight candidates are ranked without a usefulness gate;
even the first topic may have a low synthetic grade. Page/event reads and assignment computation
scale with the user's corpus, as in current coverage. This initial local endpoint is intended
for the small demonstration corpus; it does not promise a consistent historical database snapshot
across concurrent captures. The model is process-cached; BGE assignments remain provisional.

See `backend/app/artifacts/next-topic-v2-py312/README.md` for artifact trust and reproduction.
No new held-out performance evaluation was performed during the runtime refit.

The original frozen synthetic test reported NDCG@3 0.934870, NDCG@5 0.942769 and grade-2
Precision@3 0.430000, versus graph baseline NDCG@3 0.390529. These measure imitation of a
synthetic rubric on numbered batches from one generator. Labels are not independent human
preferences; the runtime refit has no separate held-out test claim. BGE was pretrained and not
fine-tuned. The logistic regression model was trained on synthetic next-topic usefulness grades.
