"""Prepare private offline benchmark inputs. No API calls, model outputs or human labels generated."""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.evaluation.benchmark_intake import (
    IntakeError,
    merge_labels,
    saved_predictions,
    write_private_new,
)
from app.evaluation.errors import EvaluationError

logger = logging.getLogger("cqa.benchmark")


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(
            2,
            "ERROR cqa.benchmark event=benchmark_intake_failed error=BENCHMARK_INVALID_ARGUMENTS\n",
        )


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    labels = commands.add_parser(
        "labels", help="Validate human-completed language files for one split"
    )
    for language in ("ru", "kz", "en"):
        labels.add_argument(f"--{language}", required=True, type=Path)
    labels.add_argument(
        "--human-signoff",
        required=True,
        action="store_true",
        help="Assert actual human completion and independent review; never supplied by AI on real data",
    )
    predictions = commands.add_parser(
        "predictions",
        help="Convert saved terminal Evaluation resources, using original only",
    )
    predictions.add_argument("--evaluations", required=True, type=Path)
    for command in (labels, predictions):
        command.add_argument(
            "--package", required=True, type=Path, help="Frozen annotation-v1 directory"
        )
        command.add_argument("--split", required=True, choices=("tune", "holdout"))
        command.add_argument(
            "--output",
            required=True,
            type=Path,
            help="New file in an existing private directory; atomic 600 creation; never overwritten",
        )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logger.info("event=benchmark_intake_started")
    try:
        if args.command == "labels":
            result = merge_labels(
                args.package,
                {"RU": args.ru, "KZ": args.kz, "EN": args.en},
                split=args.split,
            )
        else:
            result = saved_predictions(args.package, args.evaluations, split=args.split)
        write_private_new(args.output, result.model_dump(mode="json"))
    except KeyboardInterrupt:
        logger.error("event=benchmark_intake_failed error=BENCHMARK_INTERRUPTED")
        return 130
    except IntakeError as exc:
        logger.error("event=benchmark_intake_failed error=%s", exc.args[0])
        return 2
    except (
        OSError,
        UnicodeError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        EvaluationError,
    ):
        logger.error("event=benchmark_intake_failed error=BENCHMARK_INVALID_INPUT")
        return 2
    logger.info("event=benchmark_intake_completed records=%d", len(result.cases))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
