# V2 synthetic rubric imitation experiment

Run the label-blind gate from the repository root. The training command reproduces the
experiment in a fresh output directory only; the default output already contains the one-time
sealed-test evaluation and the script refuses to overwrite it:

```powershell
python -m ml.audit_next_topic_v2 --report ml/local-data/next-topic-v2-audit/report.json
python -m ml.train_next_topic_v2 --output-dir ml/local-data/next-topic-v2-model-reproduction
python -m pytest ml/tests
```

The generated V2 files and checksums were preserved. This first run selected C=0.1 from a
predeclared grid of 0.1, 1, and 10 on validation NDCG@3, breaking ties toward lower C. The
fitted scikit-learn Pipeline contains constant-zero numeric imputation (with missing indicators),
numeric standardization, categorical one-hot encoding, and regularized three-class logistic
regression. Only train rows fit the preprocessing and classifier. Eight topics are scored
independently using P(grade 1) + 2 P(grade 2), then ranked with topic-ID tie breaking. These
model probabilities are internal synthetic class outputs, not calibrated real-world usefulness.

The frozen feature order is read from V2 manifest and checked against code. The numeric/categorical
columns are fixed in code. Metadata, IDs, narrative, family, split and targets cannot enter the
feature matrix. The offline temporal adapter in `ml/next_topic_temporal.py` accepts scoped page
assignments and events, filters both event occurrence and ingestion time at the observation
cutoff, and leaves missing embeddings or unclassified pages outside topic evidence. It does not
write to the production database. Historical use needs assignment availability timestamps; do
not reinterpret current assignment as a past prediction.

The graph baseline scores exactly the prerequisite gap used by the existing rule: a topic with
fewer than two pages that is a direct prerequisite of any observed topic. Others tie at zero.
The topic-prior baseline uses mean synthetic grades for each topic in train only. Both baselines
score all eight candidates in every scenario. Metrics and per-batch diagnostics are saved in
`ml/local-data/next-topic-v2-model/evaluation.json`. The trained pipeline is saved as a trusted
local joblib artifact in the same Git-ignored directory; loading arbitrary joblib files is unsafe.

The test partition was opened once after model selection. Further tuning against its results
would invalidate its sealed status. Numbered families are batches drawn from one generator,
not independently authored cases. Results measure imitation of an explicitly synthetic rule
across these batches; they do not establish user personalization, learning outcomes, or useful
live recommendations. The model is not integrated into the live app.

The first artifact was fitted under local Python 3.10 with scikit-learn 1.7.2. The supported
Python 3.12 Docker image currently has scikit-learn 1.9.1; unpickling there produces estimator
version warnings. `load_trusted_artifact` now verifies the trusted path, SHA-256, and matching
Python minor and scikit-learn versions before loading. This artifact is for the recorded offline experiment only;
it is not portable to the current Docker runtime without a separate compatible training run.
