"""Opt-in release identity and controlled migration/seed procedure.

This is an operator guard, NOT authenticated proof that a person approved a
release. The team must record approval separately. Nothing deploys or creates a
provider resource. Migrate/seed require explicit --execute and target identity.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping
from urllib.parse import parse_qsl, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
RECORD = Path("frontend/dist/release.json")
_SHA = re.compile(r"[0-9a-f]{40}")


class ReleaseBlocked(RuntimeError):
    pass


def verify_identity(approved: str, actual: str, branch: str) -> str:
    if type(approved) is not str or _SHA.fullmatch(approved) is None:
        raise ReleaseBlocked("Set APPROVED_RELEASE_COMMIT to an approved full main commit SHA")
    if type(actual) is not str or _SHA.fullmatch(actual) is None or actual != approved:
        raise ReleaseBlocked("Actual commit does not match the approved release")
    if branch != "main":
        raise ReleaseBlocked("Only an approved main release may use these commands")
    return approved


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ReleaseBlocked("A real main checkout with verifiable Git history is required")
    return result.stdout.strip()


def checkout_identity(root: Path, environ: Mapping[str, str]) -> str:
    actual = _git(root, "rev-parse", "HEAD")
    provider_commit = environ.get("RENDER_GIT_COMMIT", actual)
    if provider_commit != actual:
        raise ReleaseBlocked("Provider commit and checked-out commit differ")
    local_branch = _git(root, "branch", "--show-current")
    branch = environ.get("RENDER_GIT_BRANCH", local_branch)
    approved = verify_identity(environ.get("APPROVED_RELEASE_COMMIT", ""), actual, branch)
    # An approved SHA must actually belong to main's fetched history. An arbitrary
    # member commit plus a manually supplied branch label is not sufficient.
    _git(root, "merge-base", "--is-ancestor", approved, "refs/remotes/origin/main")
    # Refuse modified tracked application/config files. Untracked local private
    # .env files are not printed or included in release metadata.
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ReleaseBlocked("Tracked release files have uncommitted changes")
    if _git(root, "ls-files", "--others", "--exclude-standard", "--",
            "backend/app", "backend/migrations", "frontend/src", "scripts", ".github", "render.yaml"):
        raise ReleaseBlocked("Untracked application/configuration source is not part of the approved release")
    return approved


def verify_release_record(path: Path, commit: str) -> None:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ReleaseBlocked("Build release record is unavailable") from None
    if record != {"commit": commit, "branch": "main"}:
        raise ReleaseBlocked("Built frontend and approved backend release differ")


def validate_neon_target(
    environ: Mapping[str, str], *, expected_host: str | None = None,
    expected_database: str | None = None, direct_required: bool = False,
) -> tuple[str, str]:
    if environ.get("APP_ENV") != "production":
        raise ReleaseBlocked("Production release commands require APP_ENV=production")
    try:
        raw = environ.get("DATABASE_URL", "")
        if raw != raw.strip() or any(ord(c) < 33 or ord(c) == 127 for c in raw):
            raise ValueError
        url = urlsplit(raw)
        if url.scheme != "postgresql+psycopg" or not url.username or not url.password or url.fragment:
            raise ValueError
        host = url.hostname or ""
        database = unquote(url.path.removeprefix("/"), errors="strict")
        if not host.endswith(".neon.tech") or not database or "/" in database:
            raise ValueError
        if any(ord(c) < 32 or ord(c) == 127 for c in database) or (url.port is not None and not 1 <= url.port <= 65535):
            raise ValueError
        pairs = parse_qsl(url.query, strict_parsing=True, keep_blank_values=True)
        options = dict(pairs)
        if len(pairs) != len(options) or set(options) - {"sslmode", "channel_binding", "connect_timeout"}:
            raise ValueError
        if options.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
            raise ValueError
        if "channel_binding" in options and options["channel_binding"] != "require":
            raise ValueError
        if "connect_timeout" in options and (not options["connect_timeout"].isascii() or not options["connect_timeout"].isdigit() or not 1 <= int(options["connect_timeout"]) <= 10):
            raise ValueError
        if direct_required and "-pooler." in host:
            raise ValueError
        if expected_host is not None and host != expected_host:
            raise ValueError
        if expected_database is not None and database != expected_database:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ReleaseBlocked("A matching Neon PostgreSQL/psycopg target with required TLS is required") from None
    return host, database


def probe_production_database(environ: Mapping[str, str], database: str) -> None:
    try:
        from psycopg import connect
        dsn = environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
        with connect(dsn, connect_timeout=5, autocommit=True,
                     options="-c default_transaction_read_only=on -c statement_timeout=2000") as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_setting('server_version_num')::integer")
                actual_database, version = cursor.fetchone()
        if actual_database != database or type(version) is not int or version // 10000 != 18:
            raise ValueError
    except Exception:
        raise ReleaseBlocked("Production PostgreSQL 18 target verification failed; no migration/seed started") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", required=True, choices=("build", "record", "start", "migrate", "seed"))
    parser.add_argument("--expected-host")
    parser.add_argument("--expected-database")
    parser.add_argument("--execute", action="store_true", help="Explicitly execute the already-approved migrate/seed operation")
    arguments = parser.parse_args()
    try:
        if sys.version_info[:2] != (3, 12):
            raise ReleaseBlocked("Python 3.12 is required")
        # Stage start can use immutable build metadata even when a runtime image
        # excludes .git. Provider branch/commit must then be present and match.
        if arguments.stage == "start":
            commit = verify_identity(
                os.environ.get("APPROVED_RELEASE_COMMIT", ""),
                os.environ.get("RENDER_GIT_COMMIT", ""),
                os.environ.get("RENDER_GIT_BRANCH", ""),
            )
            validate_neon_target(os.environ)
            verify_release_record(ROOT / RECORD, commit)
        else:
            commit = checkout_identity(ROOT, os.environ)
            if arguments.stage == "record":
                destination = ROOT / RECORD
                if not destination.parent.is_dir() or not (destination.parent / "index.html").is_file():
                    raise ReleaseBlocked("C's real frontend must be built before writing release metadata")
                destination.write_text(json.dumps({"commit": commit, "branch": "main"}, sort_keys=True) + "\n", encoding="utf-8")
            elif arguments.stage in {"migrate", "seed"}:
                if not arguments.execute or not arguments.expected_host or not arguments.expected_database:
                    raise ReleaseBlocked("Explicit --execute, --expected-host and --expected-database are required")
                _, database = validate_neon_target(
                    os.environ, expected_host=arguments.expected_host,
                    expected_database=arguments.expected_database, direct_required=True,
                )
                probe_production_database(os.environ, database)
                command = [sys.executable, "-m", "alembic", "upgrade", "head"] if arguments.stage == "migrate" else [sys.executable, "-m", "app.seed"]
                # A owns both implementations. Never auto-migrate or auto-seed
                # on startup/build or run migrations once per worker.
                # Keep potentially unsanitized A-owned command output out of shared logs.
                subprocess.run(command, cwd=ROOT / "backend", check=True, capture_output=True, text=True)
        print(f"Verified {arguments.stage} identity: main {commit}")
        return 0
    except ReleaseBlocked as error:
        # All ReleaseBlocked messages are constants, never offending input values.
        print(f"BLOCKED: {error}")
        return 2
    except OSError:
        print("BLOCKED: a required release file or command is unavailable")
        return 2
    except subprocess.CalledProcessError:
        print("FAIL: A-owned migration/seed command failed; do not deploy or claim success")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
