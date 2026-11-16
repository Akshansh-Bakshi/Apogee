# SYNTHETIC next-topic inference artifact

`model.joblib` contains only a fitted scikit-learn preprocessing/classifier pipeline trained on
1,600 fictional candidate rows (200 training scenarios) from synthetic-next-topic-v2. No real
browsing content, BGE weights, private evaluation, or test observations are bundled. The manifest
records the training-data checksum, fixed features, taxonomy, seed, C=0.1 and runtime versions.
This directory's generated artifact and manifest are distributed under the accompanying MIT
license. Scikit-learn, NumPy and joblib are separate runtime dependencies under their own licenses.

The original model was selected previously. This artifact is a Python 3.12 runtime refit of that
fixed configuration. No validation selection or frozen-test evaluation was repeated. Original
test metrics describe the original artifact; no independent test metrics are claimed for this refit.
Scores estimate synthetic rubric grades, not calibrated real user usefulness or mastery.

The loader has a source-pinned SHA-256 and fixed repository path. No request may provide an
artifact path. It verifies bytes before unpickling, plus versions, feature order, taxonomy,
pipeline shape and classes. Both success and failure are cached per process; restart the backend
after an intentional artifact replacement. Do not replace this binary with a downloaded pickle.

Refit from the repository root, in the existing supported image (no package upgrades):

```powershell
docker run --rm -v "${PWD}:/repo" -w /repo -e PYTHONDONTWRITEBYTECODE=1 apogee-backend python -m ml.refit_next_topic_v2 --output ml/local-data/next-topic-v2-reproduction
```

The output must be new. Required runtime: Python 3.12.14, scikit-learn 1.9.1, NumPy 2.5.3,
joblib 1.6.0. The Dockerfile and model dependency pins record these versions; inspect the new
manifest and verify compatibility after a fresh build. No
dependencies were installed or upgraded for this refit. The reproducible inputs are source,
the V2 synthetic data and its train split; private files under ml/local-data are not needed.

When packaging the project, include the shared feature/temporal modules, loader, service, schema,
route, this directory, offline refit/training helpers and synthetic V2 files. These additions are
must be included in the staged submission; an archive of the previous HEAD does not contain them.
