# Human topic annotation and evaluation

This offline workflow evaluates the existing zero-shot assignments. It does not train a
classifier, change the frozen `apogee-technical-v1` taxonomy, or write to PostgreSQL.
All outputs stay under the ignored `ml/local-data/` directory.

## 1. Create the blinded review package

With the local API and database running:

```powershell
python -m ml.prepare_topic_annotation `
  --user-id <development-user-uuid> `
  --output-dir ml/local-data/topic-review-v1
```

This creates:

- `topic-annotations.csv`: the reviewer sheet with page ID, local title/domain
  metadata, optional excerpt, and empty human decision fields. It has no model prediction.
- `topic-predictions.csv`: saved model status, topic, cosine similarity, abstention
  reason, and embedding count. Do not give this file to the initial reviewer.
- `topic-taxonomy.csv`: the eight allowed topics and fixed prerequisite edges.

Titles are whitespace-normalized and limited to 200 characters; domains to 255.
Page text is omitted by default. A reviewer must first decide that locally stored page
text may be placed in the private review sheet. Only then rerun with both:

```powershell
--include-excerpts `
--content-review-acknowledgement "I APPROVE LOCAL PAGE EXCERPTS"
```

Excerpts contain at most 280 characters from the first stored chunk. This limit is not a
secret detector. If content cannot be reviewed safely, keep the excerpt absent and mark
the row `excluded` with a reason.

## 2. Review without predictions

Open only `topic-annotations.csv` and `topic-taxonomy.csv` during initial labeling.
For each row, choose exactly one `review_status`:

- `labeled`: set one exact taxonomy ID in `human_topic` and set `reviewer_id`.
- `uncertain`: leave `human_topic` empty and explain ambiguity in `reviewer_notes`.
- `not_enough_content`: leave the topic empty and explain missing evidence.
- `excluded`: leave the topic empty and document the privacy or review reason.
- `unreviewed`: the initial state; it is never ground truth.

Mark multi-topic pages `uncertain` unless the reviewer can independently choose one
primary topic. Uncertain, insufficient, excluded, and unreviewed rows never enter metrics.

## 3. Evaluate

```powershell
python -m ml.evaluate_topics `
  --annotations ml/local-data/topic-review-v1/topic-annotations.csv `
  --predictions ml/local-data/topic-review-v1/topic-predictions.csv `
  --output ml/local-data/topic-review-v1/topic-evaluation.json
```

The evaluator joins by page ID, rejects duplicates, taxonomy mismatches, invalid topic
IDs and inconsistent statuses, and never promotes predictions to labels. It reports the
labeled sample size, abstention, confusion counts, per-class support/precision/recall/F1,
and macro-F1 over human ground-truth classes with support. A supported class missed
completely receives F1=0. Undefined precision remains null. The report includes its
small-sample limitations.

## Development corpus diagnostic

Independent human review covered 32 local pages. The frozen zero-shot assignment matched 22
human topics exactly; one prediction abstained. Exact-match agreement counting that abstention
as a non-match was 22/32 = 68.75%. Macro-F1 was 0.4994729907773386 across the six classes
represented in human labels. The 32-page corpus is small and class-imbalanced. These results
are a development-set diagnostic, not independent test-set generalization or evidence of a
trained classifier. No page-level labels, titles, URLs, or content are published here.
