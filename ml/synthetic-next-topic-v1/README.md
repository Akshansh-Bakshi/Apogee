# SYNTHETIC next-topic ranking dataset v1

Every scenario, narrative, activity record, and usefulness target in this directory is
**synthetic**. Nothing comes from an Apogee user, the development database, captured webpages,
or browsing history. The labels are simulation judgments written under a fixed rubric; they are
not user feedback, human ground truth, or evidence of recommendation quality.

The dataset supports an exploratory candidate-level learning-to-rank experiment over the frozen
`apogee-technical-v1` taxonomy. It does not modify that taxonomy or the production prerequisite
recommender. No model is trained by the generator.

## Reproduce and validate

Run from the repository root with the project's supported Python environment:

```powershell
python -m ml.generate_synthetic_next_topic
python -m ml.generate_synthetic_next_topic --validate ml/synthetic-next-topic-v1/data
python -m pytest ml/tests/test_synthetic_next_topic.py
```

Generation is deterministic with seed `20261116`; the review sample uses seed `20261117`.
The generator imports the live taxonomy definition and fails validation if topic IDs or the
taxonomy version do not match. Artifact SHA-256 values are recorded in `dataset-manifest.json`.

## Shape and splits

- 150 fictional scenarios in 15 scenario families, 10 related variants per family.
- All eight candidate topics for every scenario: 1,200 candidate rows.
- Train: 9 families, 90 scenarios, 720 rows.
- Validation: 3 families, 30 scenarios, 240 rows.
- Frozen test: 3 families, 30 scenarios, 240 rows.

Families are assigned as indivisible groups. Related variants and all eight rows from a scenario
therefore remain in one split. The test families are declared as constants in the generator and
are marked `frozen_before_training` in their manifest. Fifteen families, especially only three
test families, are too few to claim broad statistical independence. Future work should add new
independently authored families before treating this as more than an exploratory experiment.

## Artifacts

| File | Purpose |
|---|---|
| `data/scenarios.jsonl` | Fictional narratives and observed activity for all eight topics |
| `data/candidates.jsonl` | One feature and target row per scenario-topic pair |
| `data/split-*.json` | Family-grouped train, validation, and frozen-test manifests |
| `data/generation-statistics.json` | Shape, balance, coverage, split, and graph-counterexample summaries |
| `data/dataset-manifest.json` | Versions, seeds, generator path, and artifact checksums |
| `data/human-review-sample.csv` | Blinded 30-scenario, 240-row optional review sheet |
| `data/human-review-sample-synthetic-label-key.csv` | Separate synthetic label key; keep closed during review |

The review sheet contains blank `human_usefulness_target`, `reviewer_id`, and `reviewer_notes`
fields. A reviewer should open the review sheet alone, judge all eight candidates within each
scenario, and compare with the synthetic key only after finishing.

## Candidate feature contract

Each candidate row carries the dataset, feature-schema and taxonomy versions; scenario ID,
family, split, exploration state and fictional narrative; candidate topic ID; observed page and
visit counts; recency in days; topic breadth; aggregate page/visit counts; repeat-visit ratio;
candidate activity shares; prerequisite IDs and evidence counts; and two graph relationship
flags. Null recency means the fictional scenario contains no observed page for that topic.

`synthetic_usefulness_target` is ordinal:

- `0`: not useful as the next topic in this fictional context.
- `1`: potentially useful, but secondary or dependent on more context.
- `2`: strongly useful as one of the next topics; multiple candidates may receive this label.

The exact intended feature list is frozen in `dataset-manifest.json`. Training code must exclude
`scenario_id`, `scenario_family`, `split`, `scenario_narrative`, `candidate_topic_name`, and label
provenance/disclaimer fields. Narratives exist for human inspection and rubric traceability; using
their recurring template language as input would create avoidable leakage. Group all ranking rows
by `scenario_id`. The target is described in
[SYNTHETIC-LABEL-RUBRIC.md](SYNTHETIC-LABEL-RUBRIC.md).

## Validation rules

The validator checks dataset and taxonomy versions, explicit synthetic markers, unique scenario
IDs and narratives, unique scenario-candidate pairs, exactly eight valid topics per scenario,
required feature presence, label range, complete split coverage, family leakage, the frozen test
family set, minimum 15% support for every label, and a maximum 2:1 imbalance in strong-label
support between topics. It also reports graph-gap candidates assigned label 0 to demonstrate that
the labels are not copies of the prerequisite recommender.

## Appropriate conclusions

The dataset is suitable for testing whether a small supervised ranker can fit and compare methods
under this synthetic rubric, with all model selection confined to train and validation families.
It cannot establish usefulness to real users, production recommendation quality, learning gains,
fairness, calibration, or generalization to natural browsing histories. Test performance would be
performance on three held-out fictional template families, not independent real-world evidence.
