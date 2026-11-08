"""Create/check Appendix Results 1.0 from saved predictions. Never calls an API."""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.diagnostics import log_internal_error
from app.evaluation.errors import EvaluationError
from app.evaluation.submission import (
    SubmissionExportError,
    build_submission,
    project_snapshots,
    validate_submission,
)

logger = logging.getLogger("cqa.submission")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_records(path, kind):
    data = read_json(path)
    if data.get("isSuccess") is not True:
        raise SubmissionExportError("SUBMISSION_INVALID_DATASET")
    data = data["data"]
    records = data["records"]
    expected = 65 if kind == "dev" else 10
    if len(records) != expected or data["total_records"] != expected:
        raise SubmissionExportError("SUBMISSION_DATASET_SIZE_MISMATCH")
    return records


def write_json(path, document):
    """Validate first, then replace atomically; failures retain the previous file."""
    serialized = (
        json.dumps(
            document.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
        )
        + "\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".submission-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=["dev", "prod"])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--check", type=Path)
    parser.add_argument("--team-name")
    parser.add_argument("--run-directory", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    logger.info("event=submission_export_started")
    try:
        records = load_records(args.dataset, args.kind)
        if args.check:
            document = validate_submission(read_json(args.check), records)
        else:
            if not args.team_name or not args.run_directory:
                raise SubmissionExportError("SUBMISSION_SOURCES_REQUIRED")
            source_paths = {args.dataset.resolve()}
            source_paths.update(
                (run / filename).resolve()
                for run in args.run_directory
                for filename in ("labels.frozen.json", "predictions.json")
            )
            if args.output.resolve() in source_paths:
                raise SubmissionExportError("SUBMISSION_OUTPUT_IS_SOURCE")
            runs = [
                (
                    project_snapshots(read_json(run / "labels.frozen.json")),
                    read_json(run / "predictions.json"),
                )
                for run in args.run_directory
            ]
            document = build_submission(
                records=records, runs=runs, team_name=args.team_name
            )
            write_json(args.output, document)
    except SubmissionExportError as exc:
        logger.error("event=submission_export_failed error=%s", exc.args[0])
        return 2
    except (OSError, UnicodeError, ValueError, KeyError, TypeError, EvaluationError):
        logger.error("event=submission_export_failed error=SUBMISSION_INVALID_INPUT")
        return 2
    except Exception as exc:  # noqa: BLE001 - final CLI boundary must not expose private exceptions
        log_internal_error("SUBMISSION_INTERNAL_ERROR", exc)
        logger.error("event=submission_export_failed error=SUBMISSION_INTERNAL_ERROR")
        return 2
    errors = sum(row.status == "error" for row in document.results)
    logger.info(
        "event=submission_export_completed records=%d errors=%d",
        len(document.results),
        errors,
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "records": len(document.results),
                "ok": len(document.results) - errors,
                "errors": errors,
            }
        )
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    raise SystemExit(main())
