"""Trusted, process-cached inference for an explicitly synthetic rubric model."""
import hashlib
import io
import json
import platform
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.pipeline import Pipeline

from app.services.next_topic_features import FEATURES, FEATURE_VERSION
from app.services.topic_taxonomy import TAXONOMY_VERSION

ARTIFACT_DIR = Path(__file__).resolve().parents[1]/'artifacts'/'next-topic-v2-py312'
TRUSTED_SHA256 = 'c9dc747919e6a61d9439557804f6bb50f3a88eff0b79cacc000e9dd44d296a2d'


class ArtifactError(ValueError):
    pass


def load_model(directory=ARTIFACT_DIR):
    """No request-provided paths. Pin artifact bytes in source before unpickling."""
    try:
        blob = (directory/'model.joblib').read_bytes()
        meta = json.loads((directory/'manifest.json').read_text())
    except FileNotFoundError as exc:
        raise ArtifactError('artifact_missing') from exc
    except (OSError, ValueError) as exc:
        raise ArtifactError('artifact_invalid') from exc
    if not isinstance(meta, dict) or not isinstance(meta.get('versions'), dict):
        raise ArtifactError('artifact_invalid')
    if hashlib.sha256(blob).hexdigest() != TRUSTED_SHA256 or meta.get('model_sha256') != TRUSTED_SHA256:
        raise ArtifactError('artifact_untrusted')
    if (meta.get('features') != list(FEATURES) or meta.get('feature_schema_version') != FEATURE_VERSION
            or meta.get('taxonomy_version') != TAXONOMY_VERSION):
        raise ArtifactError('schema_mismatch')
    expected = dict(python=platform.python_version(), sklearn=sklearn.__version__,
                    numpy=np.__version__, joblib=joblib.__version__)
    versions = meta.get('versions', {})
    if (not isinstance(versions.get('python'), str)
            or versions['python'].split('.')[:2] != expected['python'].split('.')[:2]
            or any(versions.get(k) != expected[k] for k in ('sklearn', 'numpy', 'joblib'))):
        raise ArtifactError('runtime_mismatch')
    if meta.get('model_version') != 'synthetic-next-topic-v2-py312-refit-1':
        raise ArtifactError('schema_mismatch')
    try:
        model = joblib.load(io.BytesIO(blob))
        if (not isinstance(model, Pipeline) or model.n_features_in_ != len(FEATURES)
                or list(model.named_steps['classifier'].classes_) != [0, 1, 2]):
            raise ValueError('unexpected model shape')
    except Exception as exc:
        raise ArtifactError('artifact_invalid') from exc
    return model, meta


@lru_cache(maxsize=1)
def cached_model():
    # Cache failures too; deployment replacement requires a process restart.
    try:
        return (*load_model(), None)
    except ArtifactError as exc:
        return None, None, str(exc)


def rank(model, features):
    ids = sorted(features)
    matrix = np.asarray([[np.nan if features[t][f] is None else features[t][f]
                          for f in FEATURES] for t in ids], dtype=object)
    probabilities = model.predict_proba(matrix)
    if (probabilities.shape != (8, 3) or not np.isfinite(probabilities).all()
            or (probabilities < 0).any() or not np.allclose(probabilities.sum(axis=1), 1)):
        raise ArtifactError('prediction_invalid')
    scores = probabilities @ np.array([0., 1., 2.])
    return sorted(zip(ids, map(float, scores)), key=lambda item: (-item[1], item[0]))
