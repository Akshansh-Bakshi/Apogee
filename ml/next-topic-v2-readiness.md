# V2 production-input gate and training status

The Prompt 23 audit found that `visits >= distinct_pages` was an invalid assumption. Prompt 24
removed that check and added `ml/next_topic_temporal.py`, a read-only adapter that filters owned
page assignments and browsing events by an explicit observation cutoff. A topic can now have
assigned pages and no eligible visits. The adapter also rejects future-created events and
requires an assignment availability timestamp for retrospective use.

Run the label-blind gate from the repository root:

```powershell
python -m ml.audit_next_topic_v2 --report ml/local-data/next-topic-v2-audit/report.json
```

The repaired gate passed: eight manifest hashes matched, all 2,880 candidate feature vectors
reconstructed, and the train/validation/test split contained 200/60/100 scenarios with no
scenario or numbered-batch overlap. Among 64,620 pairs, the documented strict state-similarity
check found zero exact or near duplicates. It cannot establish statistical independence.

The V2 generated data, features, labels, checksums, and frozen test partition were preserved.
The test partition was evaluated once after validation selection. Training and metric details
are in `synthetic-next-topic-v2/TRAINING.md`; local artifacts are under Git-ignored
`ml/local-data/next-topic-v2-model/`.

The 36 numbered families are batches from one synthetic generator, not independently authored
mechanisms. Row-position perturbations are synthetic label noise, not real preferences. This
experiment measures imitation of a synthetic rubric. It does not establish live recommendation
quality or user learning outcomes. The trained artifact has not been integrated into the API.
