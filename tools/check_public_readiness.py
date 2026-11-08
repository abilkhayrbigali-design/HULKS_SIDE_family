"""Heuristic read-only Git publication audit; never a certificate of no secrets.

Scans index blobs and every commit reachable from local refs. Does not read
working .env/private files, contact a remote, rewrite history or change visibility.
Only codes, sanitized tracked paths and numeric metadata enter the report.
"""

import argparse
import json
import logging
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

logger = logging.getLogger("cqa.public_readiness")
SECRET = re.compile(
    rb"(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}"
    rb"|github_pat_[A-Za-z0-9_]{40,}|-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----)"
)
URL = re.compile(rb"https?://[^\s<>\"']+")
PRIVATE_SUFFIXES = {
    ".sqlite",
    ".sqlite3",
    ".db",
    ".wav",
    ".mp3",
    ".m4a",
    ".ogg",
    ".pem",
    ".key",
    ".log",
}
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".woff", ".woff2", ".ttf"}
PROBES = (
    ".env",
    "nested/.env.local",
    "data/private/probe.json",
    "artifacts/probe.log",
    "nested/probe.sqlite3",
)


class AuditError(Exception):
    pass


def git(root, *args):
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise AuditError from None
    if result.returncode:
        raise AuditError
    return result.stdout


def safe_path(path):
    if (
        len(path) > 240
        or any(c in path for c in "?#\r\n\x00")
        or SECRET.search(path.encode())
    ):
        return "[REDACTED_PATH]"
    return path


def private_path(path):
    value = Path(path)
    return (
        value.name == ".env"
        or (value.name.startswith(".env.") and value.name != ".env.example")
        or path.startswith(("data/private/", "artifacts/"))
        or value.suffix.lower() in PRIVATE_SUFFIXES
        or value.name.endswith((".db-wal", ".db-shm", ".sqlite3-wal", ".sqlite3-shm"))
    )


def content_codes(path, body):
    codes = set()
    if SECRET.search(body):
        codes.add(("SECRET_SHAPED_LITERAL_REVIEW", True))
    for match in URL.finditer(body):
        try:
            parsed = urlsplit(match.group().decode("utf-8", "replace"))
            signed = any(
                key.lower() in {"sig", "token", "api_key", "access_token"} and value
                for key, value in parse_qsl(parsed.query)
            )
            host = parsed.hostname or ""
        except ValueError:
            codes.add(("URL_PARSE_REVIEW", True))
            continue
        if signed:
            synthetic = host in {
                "localhost",
                "127.0.0.1",
                "example.com",
                "example.org",
                "example.net",
            } or host.endswith((".test", ".invalid", ".example"))
            codes.add(
                (
                    "SYNTHETIC_HOST_SIGNED_URL" if synthetic else "SIGNED_URL_REVIEW",
                    not synthetic,
                )
            )
    if (
        path.endswith(".json")
        and not path.startswith("data/fixtures/synthetic/")
        and re.search(rb'"(?:transcript|messages)"\s*:\s*\[', body)
        and re.search(rb'"speaker"\s*:', body)
    ):
        codes.add(("TRANSCRIPT_SHAPED_JSON_REVIEW", True))
    if Path(path).name == ".env.example" and re.search(
        rb"(?m)^[ \t]*(?:OPENAI_API_KEY|CQA_DATASET_API_URL)[ \t]*=[ \t]*[^\s#]+", body
    ):
        codes.add(("NONEMPTY_SECRET_TEMPLATE", True))
    return codes


def audit(root):
    logger.info("event=public_readiness_started")
    commits = git(root, "rev-list", "--all").decode("ascii").splitlines()
    locations = defaultdict(lambda: defaultdict(set))
    indexed = set()
    for item in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        _, oid, stage = meta.decode("ascii").split()
        if stage != "0":
            raise AuditError
        name = path.decode("utf-8", "replace")
        indexed.add((oid, name))
        locations[oid][name]
    for commit in commits:
        for item in git(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
            if not item:
                continue
            meta, path = item.split(b"\t", 1)
            _, kind, oid = meta.decode("ascii").split()
            if kind == "blob":
                locations[oid][path.decode("utf-8", "replace")].add(commit)
    findings = {}

    def add(code, blocking, oid, path, members):
        key = code, safe_path(path)
        row = findings.setdefault(
            key,
            {
                "code": code,
                "path": safe_path(path),
                "blocking": blocking,
                "objects": set(),
                "commits": set(),
                "in_index": False,
            },
        )
        row["objects"].add(oid)
        row["commits"].update(members)
        row["in_index"] |= (oid, path) in indexed

    for path in git(root, "diff", "--name-only", "-z").split(b"\0"):
        if path:
            add(
                "TRACKED_WORKTREE_CHANGE",
                True,
                "worktree",
                path.decode("utf-8", "replace"),
                set(),
            )
    scanned = skipped = 0
    for oid, paths in locations.items():
        if any(private_path(path) for path in paths):
            skipped += 1
            for path, members in paths.items():
                add("PRIVATE_PATH_IN_GIT", True, oid, path, members)
            continue  # Never read committed .env, private DB/audio/payload paths.
        size = int(git(root, "cat-file", "-s", oid))
        if size > 4 * 1024 * 1024:
            skipped += 1
            for path, members in paths.items():
                add("OVERSIZE_BLOB_NOT_SCANNED", True, oid, path, members)
            continue
        body = git(root, "cat-file", "blob", oid)
        scanned += 1
        for path, members in paths.items():
            if b"\0" in body:
                code, blocking = (
                    ("STATIC_ASSET_NOT_CONTENT_SCANNED", False)
                    if Path(path).suffix.lower() in ASSET_SUFFIXES
                    else ("BINARY_BLOB_REVIEW", True)
                )
                add(code, blocking, oid, path, members)
            else:
                for code, blocking in content_codes(path, body):
                    add(code, blocking, oid, path, members)
    ignored = 0
    for probe in PROBES:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--no-index", "-q", probe],
            capture_output=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            ignored += 1
        elif result.returncode == 1:
            add("GITIGNORE_GAP", True, "ignore", ".gitignore", set())
        else:
            raise AuditError
    # This is an intentionally limited static check, not Docker's full pattern interpreter.
    docker = root / ".dockerignore"
    patterns = (
        {line.strip() for line in docker.read_text().splitlines()}
        if docker.is_file()
        else set()
    )
    if not {".env", "data/private", "artifacts"} <= patterns or any(
        rule.startswith("!") and rule != "!.env.example" for rule in patterns
    ):
        add("DOCKERIGNORE_REVIEW", True, "ignore", ".dockerignore", set())
    output = []
    for row in sorted(findings.values(), key=lambda item: (item["code"], item["path"])):
        output.append(
            {
                key: value
                for key, value in row.items()
                if key not in {"objects", "commits"}
            }
            | {
                "object_count": len(row["objects"]),
                "containing_commit_count": len(row["commits"]),
            }
        )
    blocking = sum(item["blocking"] for item in output)
    logger.log(
        logging.WARNING if blocking else logging.INFO,
        "event=public_readiness_completed records=%d errors=%d",
        scanned,
        blocking,
    )
    return {
        "status": "REVIEW_REQUIRED" if blocking else "NO_DETECTED_BLOCKERS",
        "commits_scanned": len(commits),
        "unique_blobs_scanned": scanned,
        "unique_blobs_skipped": skipped,
        "indexed_files": len(indexed),
        "gitignore_probes_passed": ignored,
        "gitignore_probes_total": len(PROBES),
        "blocking_findings": blocking,
        "findings": output,
        "limitations": [
            "HEURISTIC_NOT_SECRET_CERTIFICATION",
            "UNTRACKED_FILES_NOT_SCANNED",
            "UNREACHABLE_OBJECTS_NOT_SCANNED",
            "DOCKERIGNORE_STATIC_CHECK_ONLY",
            "REMOTE_VISIBILITY_UNCHANGED",
            "HUMAN_PROVENANCE_NOT_VERIFIED",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    try:
        report = audit(args.repo)
    except (AuditError, OSError, ValueError, subprocess.TimeoutExpired):
        logger.error("event=public_readiness_failed error=PUBLIC_READINESS_SCAN_FAILED")
        print(json.dumps({"status": "ERROR", "code": "PUBLIC_READINESS_SCAN_FAILED"}))
        return 2
    print(json.dumps(report, ensure_ascii=True))
    return 1 if report["blocking_findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
