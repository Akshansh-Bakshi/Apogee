"""Evaluate saved zero-shot topic predictions against completed independent human labels."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ml.topic_annotation import (
    ANNOTATION_FIELDS, PREDICTION_FIELDS, evaluate, read_csv, write_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate(
            read_csv(args.annotations, ANNOTATION_FIELDS),
            read_csv(args.predictions, PREDICTION_FIELDS),
        )
        if args.output:
            write_report(args.output, report)
            print(f"wrote topic evaluation report: {args.output}")
        else:
            print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(f"topic evaluation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
