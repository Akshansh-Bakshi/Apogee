"""Refit the preselected V2 configuration on TRAIN ONLY in the deployment runtime."""
import argparse
import hashlib
import json
import platform
from pathlib import Path

import joblib
import numpy as np
import sklearn

from ml.train_next_topic_v2 import pipeline, matrix, read_rows
from ml.synthetic_next_topic_v2 import FEATURES, FEATURE_VERSION, SEED, VERSION, taxonomy


def refit(data: Path, output: Path):
    if platform.python_version_tuple()[:2] != ('3', '12'):
        raise ValueError('refit requires supported Python 3.12 runtime')
    if output.exists():
        raise FileExistsError('use a new output directory; artifacts are immutable')
    manifest = json.loads((data/'manifest.json').read_text())
    candidate_bytes = (data/'candidates.jsonl').read_bytes()
    digest = hashlib.sha256(candidate_bytes).hexdigest()
    if digest != manifest['artifacts']['candidates.jsonl'] or manifest['feature_fields'] != list(FEATURES):
        raise ValueError('frozen training data or feature contract mismatch')
    split_path = data/'split-train.json'
    if hashlib.sha256(split_path.read_bytes()).hexdigest() != manifest['artifacts']['split-train.json']:
        raise ValueError('training split checksum mismatch')
    ids = set(json.loads(split_path.read_text())['scenario_ids'])
    rows = read_rows(data/'candidates.jsonl', ids)
    if len(ids) != 200 or len(rows) != 1600 or any(r['split'] != 'train' for r in rows):
        raise ValueError('unexpected training partition')
    model = pipeline(0.1)
    model.fit(matrix(rows), [r['synthetic_usefulness_target'] for r in rows])
    output.mkdir(parents=True)
    joblib.dump(model, output/'model.joblib')
    metadata = dict(model_version='synthetic-next-topic-v2-py312-refit-1',
        dataset_version=VERSION, feature_schema_version=FEATURE_VERSION,
        taxonomy_version=taxonomy()[0], features=list(FEATURES), seed=SEED, C=0.1,
        training_scenarios=200, training_rows=1600, dataset_sha256=digest,
        training_split_sha256=hashlib.sha256(split_path.read_bytes()).hexdigest(),
        model_sha256=hashlib.sha256((output/'model.joblib').read_bytes()).hexdigest(),
        versions=dict(python=platform.python_version(), sklearn=sklearn.__version__,
                      numpy=np.__version__, joblib=joblib.__version__),
        provenance='SYNTHETIC rubric imitation; fixed configuration; train-only runtime refit; no new test evaluation')
    (output/'manifest.json').write_text(json.dumps(metadata, indent=2, sort_keys=True)+'\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('ml/synthetic-next-topic-v2/data'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    refit(args.data, args.output)
