"""Fail loudly when shared components are absent; never turn missing work green."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]

_BACKEND = (
    "backend/requirements.in", "backend/requirements.txt", "backend/pyproject.toml",
    "backend/alembic.ini", "backend/migrations/env.py", "backend/app/main.py",
    "backend/app/config.py", "backend/app/db.py", "backend/app/models.py",
    "backend/app/schemas.py", "backend/app/errors.py", "backend/app/seed.py",
    "backend/app/api/flags.py", "backend/app/services/flags.py",
    "backend/app/repositories/flags.py", "backend/app/api/evaluation.py",
    "backend/app/services/evaluation.py", "backend/app/domain/evaluator.py",
    "client/feature_flag_client.py",
)
_FRONTEND = ("frontend/package.json", "frontend/package-lock.json", "frontend/src/App.tsx")


def missing_components(root: Path, scope: str) -> list[str]:
    issues = []
    if scope in {"backend", "all"}:
        for relative in _BACKEND:
            if not (root / relative).is_file():
                issues.append(f"Missing shared component: {relative}")
        lock = root / "backend/requirements.txt"
        if lock.is_file():
            text = lock.read_text(encoding="utf-8")
            if "==" not in text or "--hash=sha256:" not in text:
                issues.append("A's requirements.txt must contain exact pins and hashes")
        if not any((root / "backend/migrations/versions").glob("*.py")):
            issues.append("Missing A-owned initial Alembic revision")
        if not any((root / "client/tests").glob("test_*.py")):
            issues.append("Missing B-owned helper tests")
        for relative in ("uv.lock", "backend/uv.lock"):
            lock_path = root / relative
            if lock_path.exists():
                try:
                    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
                    # Preserve the upstream three-line metadata stub. It has no
                    # packages, is not a dependency set and is never installed.
                    metadata_only = (
                        data.get("version") == 1
                        and set(data) <= {"version", "revision", "requires-python"}
                        and data.get("requires-python") == ">=3.12"
                    )
                except (ValueError, OSError):
                    metadata_only = False
                if not metadata_only:
                    issues.append("An additional uv.lock conflicts with the shared requirements workflow")
    if scope in {"frontend", "all"}:
        for relative in _FRONTEND:
            if not (root / relative).is_file():
                issues.append(f"Missing shared component: {relative}")
        package = root / "frontend/package.json"
        if package.is_file():
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
                scripts = data.get("scripts", {})
                for name in ("typecheck", "test", "build"):
                    if type(scripts.get(name)) is not str or not scripts[name].strip():
                        issues.append(f"Missing C-owned npm script: {name}")
            except (ValueError, AttributeError):
                issues.append("Invalid frontend package.json")
        lock = root / "frontend/package-lock.json"
        if lock.is_file():
            try:
                data = json.loads(lock.read_text(encoding="utf-8"))
                if type(data.get("lockfileVersion")) is not int or data["lockfileVersion"] < 2:
                    issues.append("A committed modern frontend package-lock.json is required")
            except (ValueError, AttributeError):
                issues.append("Invalid frontend package-lock.json")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("backend", "frontend", "all"), default="all")
    arguments = parser.parse_args()
    issues = missing_components(ROOT, arguments.scope)
    if arguments.scope in {"backend", "all"} and sys.version_info[:2] != (3, 12):
        issues.insert(0, "Python 3.12 is required; no silent runtime substitution")
    if issues:
        for issue in issues:
            print(f"BLOCKED: {issue}")
        return 2
    print("Shared files present. This is NOT evidence that their tests or migrations pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
