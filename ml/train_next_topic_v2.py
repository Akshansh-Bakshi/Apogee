"""Offline synthetic V2 rubric-imitation experiment; trusted local artifacts only."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.audit_next_topic_v2 import audit
from ml.synthetic_next_topic_v2 import FEATURES, SEED, VERSION

GRID = (0.1, 1.0, 10.0)
CATEGORICAL = ("candidate_topic_id", "prerequisite_evidence_level")
NUMERIC = tuple(name for name in FEATURES if name not in CATEGORICAL)
NUMERIC_INDEX = [FEATURES.index(name) for name in NUMERIC]
CATEGORICAL_INDEX = [FEATURES.index(name) for name in CATEGORICAL]


def read_rows(path, allowed_ids):
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row["scenario_id"] in allowed_ids:
                rows.append(row)
    return rows


def matrix(rows):
    result = []
    for row in rows:
        if any(field not in row for field in FEATURES):
            raise ValueError("missing frozen model feature")
        result.append([np.nan if row[name] is None else row[name] for name in FEATURES])
    return np.asarray(result, dtype=object)


def pipeline(c):
    prep = ColumnTransformer([
        ("numeric", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value=0,
                                                     add_indicator=True)),
                              ("scale", StandardScaler())]), NUMERIC_INDEX),
        ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_INDEX),
    ], remainder="drop")
    return Pipeline([("features", prep), ("classifier", LogisticRegression(
        C=c, max_iter=2000, random_state=SEED, solver="lbfgs"))])


def score_model(model, rows):
    probabilities = model.predict_proba(matrix(rows))
    classes = model.named_steps["classifier"].classes_
    return probabilities @ np.array(classes, dtype=float)


def dcg(labels):
    return sum((2**int(label)-1)/np.log2(rank+2) for rank, label in enumerate(labels))


def metrics(rows, scores):
    groups = defaultdict(list)
    for row, score in zip(rows, scores):
        groups[row["scenario_id"]].append((row, float(score)))
    if any(len(group) != 8 for group in groups.values()):
        raise ValueError("each scenario requires exactly eight candidates")
    per_family = defaultdict(list)
    per_scenario = []
    for sid, group in sorted(groups.items()):
        ordered = sorted(group, key=lambda item: (-item[1], item[0]["candidate_topic_id"]))
        actual = [item[0]["synthetic_usefulness_target"] for item in ordered]
        ideal = sorted(actual, reverse=True)
        result = {f"ndcg@{k}": dcg(actual[:k])/dcg(ideal[:k]) if dcg(ideal[:k]) else 0.0
                  for k in (3, 5)}
        result["precision@3"] = sum(label == 2 for label in actual[:3])/3
        result["scenario_id"] = sid
        result["top_topic"] = ordered[0][0]["candidate_topic_id"]
        result["top_grade"] = actual[0]
        family = ordered[0][0]["scenario_family"]
        per_family[family].append(result)
        per_scenario.append(result)
    names = ("ndcg@3", "ndcg@5", "precision@3")
    mean = lambda group: {name: round(float(np.mean([item[name] for item in group])), 6)
                          for name in names}
    return {"overall": mean(per_scenario), "per_family": {name: mean(group)
            for name, group in sorted(per_family.items())},
            "scenario_count": len(per_scenario),
            "top_candidate_grade_0_count": sum(item["top_grade"] == 0 for item in per_scenario),
            "per_scenario": per_scenario}


def topic_prior(train_rows, rows):
    totals = defaultdict(list)
    for row in train_rows:
        totals[row["candidate_topic_id"]].append(row["synthetic_usefulness_target"])
    return [float(np.mean(totals[row["candidate_topic_id"]])) for row in rows]


def graph_rule(rows):
    # Production prerequisite heuristic only: sparse direct prerequisite of observed topic.
    # All other candidates tie at zero, with topic-ID tie breaking in metrics().
    return [int(row["candidate_is_graph_gap"]) for row in rows]


def summary_only(result):
    return {key: value for key, value in result.items() if key != "per_scenario"}


def load_trusted_artifact(path: Path, trusted_directory: Path):
    """Call only for an explicitly trusted local artifact; pickle/joblib can run code."""
    resolved = path.resolve(strict=True)
    root = trusted_directory.resolve(strict=True)
    if root not in resolved.parents or resolved.suffix != ".joblib":
        raise ValueError("model must be a trusted local joblib within artifact directory")
    report = json.loads((root/"evaluation.json").read_text(encoding="utf-8"))
    fitted_python = report["versions"]["python"].split(".")[:2]
    running_python = platform.python_version().split(".")[:2]
    if fitted_python != running_python:
        raise ValueError("Python minor version differs from fitted artifact; refusing unsafe load")
    if report["versions"]["scikit_learn"] != sklearn.__version__:
        raise ValueError("scikit-learn version differs from fitted artifact; refusing unsafe load")
    if hashlib.sha256(resolved.read_bytes()).hexdigest() != report["model_sha256"]:
        raise ValueError("model artifact checksum mismatch")
    return joblib.load(resolved)


def train(data_dir: Path, output_dir: Path):
    if (output_dir/"evaluation.json").exists():
        raise FileExistsError("sealed test was already evaluated in this output directory")
    gate = audit(data_dir)
    if gate["gate"] != "passed":
        raise ValueError("V2 production parity gate blocked training: " + ", ".join(gate["blockers"]))
    manifest = json.loads((data_dir/"manifest.json").read_text(encoding="utf-8"))
    if tuple(manifest["feature_fields"]) != FEATURES or manifest["dataset_version"] != VERSION:
        raise ValueError("frozen feature/dataset contract mismatch")
    ids = {split: set(json.loads((data_dir/f"split-{split}.json").read_text(
        encoding="utf-8"))["scenario_ids"]) for split in ("train", "validation", "test")}
    path = data_dir/"candidates.jsonl"
    train_rows = read_rows(path, ids["train"])
    validation_rows = read_rows(path, ids["validation"])
    training_labels = [row["synthetic_usefulness_target"] for row in train_rows]
    validation = {}
    candidates = {}
    for c in GRID:
        model = pipeline(c)
        model.fit(matrix(train_rows), training_labels)
        validation[str(c)] = summary_only(metrics(validation_rows, score_model(model, validation_rows)))
        candidates[c] = model
    selected_c = sorted(GRID, key=lambda c: (-validation[str(c)]["overall"]["ndcg@3"], c))[0]
    model = candidates[selected_c]  # trained on train only; preprocessing frozen before test
    train_results = summary_only(metrics(train_rows, score_model(model, train_rows)))
    validation_results = validation[str(selected_c)]
    validation_baselines = {
        "topic_prior": summary_only(metrics(validation_rows, topic_prior(train_rows, validation_rows))),
        "graph_rule": summary_only(metrics(validation_rows, graph_rule(validation_rows))),
    }
    # Final sealed-test read happens once, after every choice above is fixed.
    test_rows = read_rows(path, ids["test"])
    test_results = summary_only(metrics(test_rows, score_model(model, test_rows)))
    test_baselines = {
        "topic_prior": summary_only(metrics(test_rows, topic_prior(train_rows, test_rows))),
        "graph_rule": summary_only(metrics(test_rows, graph_rule(test_rows))),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact = output_dir/"trusted-local-v2-logistic.joblib"
    joblib.dump(model, artifact)
    result = {
        "synthetic": True, "interpretation": "Rubric imitation on synthetic numbered batches only",
        "dataset_version": VERSION, "taxonomy_version": manifest["taxonomy_version"],
        "feature_schema_version": manifest["feature_schema_version"], "features": list(FEATURES),
        "seed": SEED, "grid_c": GRID, "selected_c": selected_c,
        "selection_rule": "highest validation NDCG@3; smaller C breaks ties",
        "training_label_counts": dict(Counter(str(item) for item in training_labels)),
        "validation_grid": validation, "train": train_results,
        "validation": validation_results, "validation_baselines": validation_baselines,
        "test": test_results, "test_baselines": test_baselines,
        "dataset_candidate_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "versions": {"python": platform.python_version(), "scikit_learn": sklearn.__version__,
                     "numpy": np.__version__, "joblib": joblib.__version__},
    }
    (output_dir/"evaluation.json").write_text(json.dumps(result, indent=2, sort_keys=True)+"\n",
                                               encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("ml/synthetic-next-topic-v2/data"))
    parser.add_argument("--output-dir", type=Path, default=Path("ml/local-data/next-topic-v2-model"))
    args = parser.parse_args()
    report = train(args.data_dir, args.output_dir)
    print(json.dumps({key: report[key] for key in ("selected_c", "train", "validation", "test")},
                     indent=2))


if __name__ == "__main__":
    main()
