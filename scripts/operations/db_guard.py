"""Read-only PostgreSQL test-target preflight; NOT a replacement migration harness.

The test harness must recheck guards before destructive test setup/cleanup,
use the verified TEST_DATABASE_URL, and never overwrite DATABASE_URL to select it.
No function in this file migrates, truncates, drops, seeds, or creates anything.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import ipaddress
import json
import os
from typing import Callable, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit


class SafetyError(RuntimeError):
    """Safe diagnostic: never include DSNs, passwords, or the original exception."""


@dataclass(frozen=True)
class DatabaseIdentity:
    host: str
    port: int
    database: str


@dataclass(frozen=True)
class SafeTestSettings:
    identity: DatabaseIdentity
    test_url: str = field(repr=False)


def _host_identity(host: str) -> str:
    host = host.lower()
    if host == "localhost":
        return "loopback"
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if getattr(address, "scope_id", None):
        raise SafetyError("Scoped database hosts are not permitted")
    return "loopback" if address.is_loopback else address.compressed


def database_identity(raw: str) -> DatabaseIdentity:
    try:
        if type(raw) is not str or not raw or raw != raw.strip() or any(ord(c) < 33 or ord(c) == 127 for c in raw):
            raise ValueError
        parsed = urlsplit(raw)
        if parsed.scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError
        if not parsed.hostname or not parsed.username or parsed.fragment:
            raise ValueError
        # URL query overrides can silently redirect libpq to a different host,
        # service or database. Only harmless, bounded options are accepted here.
        options = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
        seen = set()
        for key, value in options:
            if key in seen:
                raise ValueError
            seen.add(key)
            if key == "sslmode" and value in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
                continue
            if key == "channel_binding" and value in {"disable", "prefer", "require"}:
                continue
            if key == "connect_timeout" and value.isascii() and value.isdigit() and 1 <= int(value) <= 5:
                continue
            raise ValueError
        database = unquote(parsed.path.removeprefix("/"), errors="strict")
        if not database or "/" in database or any(ord(c) < 32 or ord(c) == 127 for c in database):
            raise ValueError
        host = parsed.hostname
        if "%" in host or "," in host or host != host.strip():
            raise ValueError
        port = 5432 if parsed.port is None else parsed.port
        if not 1 <= port <= 65535:
            raise ValueError
        return DatabaseIdentity(_host_identity(host), port, database)
    except (ValueError, UnicodeError, AttributeError):
        raise SafetyError("A valid explicit PostgreSQL database URL is required") from None


def require_safe_test_database(environ: Mapping[str, str]) -> SafeTestSettings:
    if environ.get("APP_ENV") != "test":
        raise SafetyError("APP_ENV must be test before test-database access")
    test_url = environ.get("TEST_DATABASE_URL", "")
    development_url = environ.get("DATABASE_URL", "")
    test = database_identity(test_url)
    development = database_identity(development_url)
    if test.host != "loopback":
        raise SafetyError("The default test harness permits only loopback database hosts")
    if test.database != "feature_flags_test":
        raise SafetyError("The test database name must be feature_flags_test")
    if test == development:
        raise SafetyError("Development and test database identities must be distinct")
    return SafeTestSettings(identity=test, test_url=test_url)


def probe_test_database(settings: SafeTestSettings, connect: Callable | None = None) -> dict:
    """Verify actual server version/DB with a read-only connection before mutation."""
    if connect is None:
        try:
            from psycopg import connect
        except ImportError:
            raise SafetyError("Install the shared pinned backend requirements before a DB probe") from None
    dsn = settings.test_url.replace("postgresql+psycopg://", "postgresql://", 1)
    try:
        with connect(
            dsn, connect_timeout=2, autocommit=True,
            options="-c default_transaction_read_only=on -c statement_timeout=2000",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_database(), current_setting('server_version_num')::integer")
                database, version_number = cursor.fetchone()
    except Exception:
        raise SafetyError("Unable to verify the isolated PostgreSQL test database") from None
    if database != settings.identity.database:
        raise SafetyError("Connected database does not match the verified test target")
    if type(version_number) is not int or version_number // 10000 != 18:
        raise SafetyError("PostgreSQL server major version 18 is required")
    return {"database": database, "server_major": 18, "host_class": "loopback", "port": settings.identity.port}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--connect", action="store_true", help="Also verify the actual DB/version using a read-only connection")
    arguments = parser.parse_args()
    try:
        settings = require_safe_test_database(os.environ)
        report = probe_test_database(settings) if arguments.connect else {
            "database": settings.identity.database, "host_class": settings.identity.host,
            "port": settings.identity.port, "server_major": "NOT_VERIFIED",
        }
    except SafetyError as error:
        print(f"BLOCKED: {error}")
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
