"""Compare saved predictions with external human labels. No API calls or paid operations."""

import argparse
import json
import logging
import sys
from pathlib import Path

# Runnable from any cwd after `uv sync --project backend --locked`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.evaluation.benchmark import compare_predictions
from app.evaluation.errors import EvaluationError

logger = logging.getLogger("cqa.benchmark")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--split", required=True, choices=["tune", "holdout"])
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        predictions = json.loads(args.predictions.read_text(encoding="utf-8"))
        report = compare_predictions(labels, predictions, split=args.split)
    except (OSError, UnicodeError, ValueError, EvaluationError):
        logger.error("event=benchmark_failed error=BENCHMARK_INVALID_INPUT")
        return 2
    logger.info("event=benchmark_completed records=%d", report["overall"]["cases"])
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
