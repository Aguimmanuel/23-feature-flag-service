#!/usr/bin/env bash
# GitHub-hosted CI only. No Docker, developer machine changes, or production DB.
set -euo pipefail
if [[ "${GITHUB_ACTIONS:-}" != true || -z "${RUNNER_TEMP:-}" ]]; then
  printf '%s\n' 'BLOCKED: this provisioning command is restricted to a disposable GitHub runner' >&2
  exit 2
fi

BIN=/usr/lib/postgresql/18/bin
if [[ ! -x "$BIN/postgres" ]]; then
  # Official PGDG packages, restricted to the declared ubuntu-24.04 runner.
  # Do not replace an existing cluster: provision a separate ephemeral one below.
  . /etc/os-release
  if [[ "${ID:-}" != ubuntu || "${VERSION_CODENAME:-}" != noble ]]; then
    printf '%s\n' 'BLOCKED: expected ubuntu-24.04 native PostgreSQL runner' >&2
    exit 2
  fi
  sudo install -d /usr/share/keyrings /etc/postgresql-common
  curl --fail --silent --show-error --location --proto '=https' \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/postgresql-ci.gpg
  printf '%s\n' 'deb [signed-by=/usr/share/keyrings/postgresql-ci.gpg] https://apt.postgresql.org/pub/repos/apt noble-pgdg main' \
    | sudo tee /etc/apt/sources.list.d/postgresql-ci.list >/dev/null
  # This affects only the throwaway runner; no default system cluster is needed.
  printf '%s\n' 'create_main_cluster = false' \
    | sudo tee /etc/postgresql-common/createcluster.conf >/dev/null
  sudo apt-get update -qq
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends postgresql-18
fi

DATA="$RUNNER_TEMP/feature-flags-pg18-data"
SOCKET="$RUNNER_TEMP/feature-flags-pg18-socket"
if [[ -e "$DATA" || -e "$SOCKET" ]]; then
  printf '%s\n' 'BLOCKED: disposable CI database paths already exist; use a fresh job' >&2
  exit 2
fi
mkdir -m 700 "$SOCKET"
"$BIN/initdb" -D "$DATA" -U postgres --auth-local=trust --auth-host=scram-sha-256 \
  --no-locale --encoding=UTF8 >/dev/null
"$BIN/pg_ctl" -D "$DATA" -l "$RUNNER_TEMP/feature-flags-pg18.log" \
  -o "-h 127.0.0.1 -p 55432 -k $SOCKET -c log_min_error_statement=panic" -w start
version=$("$BIN/psql" -h "$SOCKET" -p 55432 -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c 'SHOW server_version_num;')
test "$((version / 10000))" = 18
"$BIN/psql" -h "$SOCKET" -p 55432 -U postgres -d postgres -v ON_ERROR_STOP=1 <<'SQL'
CREATE ROLE feature_flags_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD 'ci-disposable-app-only';
CREATE DATABASE feature_flags_dev OWNER feature_flags_app;
CREATE DATABASE feature_flags_test OWNER feature_flags_app;
SQL
printf '%s\n' 'Disposable PostgreSQL 18 databases ready on loopback:55432; no production target used.'
