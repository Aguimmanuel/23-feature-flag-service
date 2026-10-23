# Feature Flag Service

## Project Summary
**Category:** Developer Tools & Automation  
**Difficulty:** Intermediate  
**Suggested team split:** Flag API, evaluation SDK, admin UI, audit logs 

## Description
This project is a good fit for a small team that wants to build something real and usable in a short amount of time. It focuses on one clear feature, clean data flow, and a simple user experience that can be demoed without extra fluff. The goal is to turn a good idea into a working MVP with a solid backend, a basic interface, and a realistic set of edge cases.

## Scope
Toggle features by environment, user group, or percentage rollout.

## Core Features
- Deliver the main user flow from start to finish.
- Support the required data model and user interactions.
- Handle validation, edge cases, and error states cleanly.
- Include basic monitoring, feedback, or reporting where relevant.
- Make the app easy to explain during a live demo.

## Deliverables
- A working deployed application or API demo
- A clear README with setup instructions and environment variables
- A minimal database schema or data model definition
- UI screens or API endpoints for the core MVP
- A basic test strategy covering the happy path and one major failure path
- A short demo script explaining the architecture, choices, and trade-offs

## Suggested Architecture
- Frontend: simple dashboard, form-based interface, or lightweight visual layer
- Backend: API or service layer for business logic and validation
- Data layer: database, in-memory persistence, or structured file storage for MVP use
- Optional extras: auth, async jobs, scheduling, WebSockets, caching, or notifications depending on the project

## Learning Outcomes
Configuration, deterministic rollout, caching

## Recommended MVP Checklist
1. Define the main user flow and success criteria.
2. Build the data model and core backend logic.
3. Connect the UI or client to the main application flow.
4. Add key validation, security checks, and realistic error states.
5. Test the happy path and at least one important edge case.
6. Deploy the app and document the setup clearly.

## Free Deployment Options
Vercel or Netlify for the frontend; Render or Railway for the backend and job runner; GitHub Pages for docs.

## Good Free Hosting Choices
- Static frontend: Vercel, Netlify, or GitHub Pages
- API/backend: Render, Railway, or Fly.io
- Database/realtime services: Supabase, Neon, Firebase, or Cloudflare D1
- Documentation/demo pages: GitHub Pages, Cloudflare Pages, or Vercel

## Typical Tech Stack
- Frontend: React, Next.js, plain HTML/JS, or similar lightweight UI tooling
- Backend: Node.js, Python (Flask/FastAPI), or Java/Spring Boot
- Database: Postgres, SQLite, Supabase, or a simple file-based store
- Real-time layer: WebSockets, polling, or background workers if needed

## Final Demo Expectations
- Provide a working URL with sample or seeded data
- Show one clear end-to-end flow from start to finish
- Explain the most important technical decisions and trade-offs
- Include screenshots, screen recordings, or a brief live walk-through
- Highlight what was completed in the MVP and what would be next if the project continued

## Next Improvements
- Add authorization, auditing, or stronger validation
- Improve test coverage and resilience
- Add analytics, metrics, or observability
- Expand functionality once the core MVP is stable

---

# Flagboard — Implemented Project

The assignment brief above is preserved. Flagboard manages feature flags by environment, group and percentage rollout. A consuming application uses its boolean decision to show or hide a feature; this project does not include a separate checkout application.

**Live application:** https://flagboard-service.onrender.com/

**Docs:** [Demo](docs/DEMO.md) · [API contract](docs/api-contract.md) · [Database schema](docs/database-schema.md)

## Features and architecture

- Create flags with independent `development`, `staging` and `production` settings.
- Evaluate saved settings: disabled overrides everything; otherwise group match **OR** percentage inclusion enables the feature.
- Reject stale configuration saves, archive flags without losing history, and commit changes with their audit events.
- Separate admin and evaluation credentials; dashboard tokens stay in memory and clear on refresh.

```text
React/TypeScript UI → FastAPI → SQLAlchemy/psycopg → PostgreSQL 18
                         ↑
                  Python HTTPX client
```

Vite provides local development/build tooling. Alembic manages schema migrations. Locally, Vite proxies `/api` and `/health` to FastAPI. In production, Render serves the built UI and API together; Neon stores the data.

Percentage rollout uses a stable SHA-256 bucket derived from `flag_key:user_id`, not a new random choice per request. Evaluation reads persisted settings without a cache and does not add audit events.

## Local setup

Use **Python 3.12**, **Node 24** and native **PostgreSQL 18**. Docker is not required. The Python environment installs dependencies—not the database server. The commands below use Bash on Ubuntu; other operating systems have not been verified.

### 1. Get the code and prepare PostgreSQL

```bash
git clone https://github.com/Aguimmanuel/23-feature-flag-service.git
cd 23-feature-flag-service
```

If PostgreSQL 18 is absent, follow the [official Ubuntu installation instructions](https://www.postgresql.org/download/linux/ubuntu/). Verify the running server, not just the client. These examples use port 5432; use your PostgreSQL 18 cluster's actual port throughout.

```bash
sudo -u postgres psql --port=5432 -c 'SHOW server_version;'
```

Create these **only if they do not already exist**. Keep existing databases; do not reset them to repeat setup.

```bash
sudo -u postgres createuser --port=5432 --pwprompt --no-superuser --no-createdb --no-createrole feature_flags_app
sudo -u postgres createdb --port=5432 --owner=feature_flags_app --encoding=UTF8 --template=template0 feature_flags_dev
sudo -u postgres createdb --port=5432 --owner=feature_flags_app --encoding=UTF8 --template=template0 feature_flags_test
```

### 2. Install backend dependencies

From the repository root, choose **one** method. Both use the same pinned, hashed requirements.

**Standard venv/pip** (Python 3.12 and its venv module must be installed):

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.txt
```

**Optional uv** (`.python-version` selects Python 3.12):

```bash
cd backend
uv venv
source .venv/bin/activate
uv pip install --require-hashes -r requirements.txt
```

Use `requirements.txt`, not `uv sync`; the committed uv metadata is not the installation source.

### 3. Configure and start the backend

Inside `backend/`, retain an existing working `.env`. For a new setup:

```bash
test -e .env || (umask 077; cp .env.example .env)
chmod 600 .env
```

Edit `.env` privately: set the local database password/port in both URLs, URL-encoding special password characters. Keep `DATABASE_URL` on `feature_flags_dev` and `TEST_DATABASE_URL` on the separate disposable `feature_flags_test`. Replace both token placeholders with **different random secrets**, and keep `APP_ENV=development`. Never commit this file or place secrets in `VITE_*` variables.

Optional settings: `ALLOWED_ORIGINS` accepts explicit comma-separated origins (no wildcard); `DB_POOL_SIZE` and `DB_MAX_OVERFLOW` default to 5 each. Environment variables override `.env`.

With the Python environment active:

```bash
python -m alembic upgrade head
python -m alembic check
python -m app.seed  # Optional synthetic sample data.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

API documentation: http://127.0.0.1:8000/docs. Migrations create tables; startup does not migrate or seed automatically. Seed leaves existing keys unchanged, including archived flags. `new-checkout` starts at development 100%, staging `beta` OR 25%, production disabled; `search-preview` starts disabled everywhere.

### 4. Start the frontend

In another terminal, from the repository root:

```bash
cd frontend
npm ci
npm run dev -- --port 5173
```

Open http://localhost:5173/ and enter the local admin token privately. FastAPI must be running on port 8000. Save configuration before evaluating; unsaved edits do not affect decisions.

For a single-server local preview, run `npm run build` in `frontend/`, then restart FastAPI and open http://127.0.0.1:8000/. Without that build, the backend root can return 404 while `/docs` still works.

## Testing

With the backend Python environment active, from the repository root:

```bash
APP_ENV=test python -m pytest -c backend/pyproject.toml backend/tests client/tests -q
```

**Persistence tests delete disposable test data.** The harness requires the separate local `feature_flags_test` database, explicit test mode, PostgreSQL 18 verification and a suite lock. Never target Neon or the development database, bypass safety refusals, or use parallel pytest workers.

Frontend checks:

```bash
cd frontend
npm run typecheck
npm test -- --run
npm run build
```

Then rerun backend/client tests from the root with `frontend/dist` still present to check combined serving behaviour.

Real-browser tests require both local servers. From `frontend/`, install the automation browser once if needed with `npx playwright install chromium`, then:

```bash
read -r -s -p 'Local ADMIN_TOKEN: ' ADMIN_TOKEN; echo
export ADMIN_TOKEN
npm run test:e2e
unset ADMIN_TOKEN
```

An installed Chrome can instead be selected with `channel: "chrome",` in the existing Playwright `use` block; keep that change local. If Chromium reports missing Linux libraries, review them before using `npx playwright install-deps chromium`. Normal app use needs no automation browser. Browser tests create/archive their own flags; never run them against the hosted service. Review any captured images before sharing.

**Recorded verification, 22 October 2026:** 329 backend/client tests + 138 subtests, 15 frontend tests, five local browser tests, typecheck and build passed. One upstream deprecation warning remained. Covered edge cases include disabled precedence, rollout boundaries, stale saves, audit rollback, archived keys and malformed client responses. [Released-main CI](https://github.com/Aguimmanuel/23-feature-flag-service/actions/runs/39813792505) passed; browser tests were separate, not a CI job. Hosted create/save/evaluate/audit and refresh persistence were manually verified. These are previous results, not a fresh run for this documentation update.

## Python client

From the repository root with the backend dependencies installed, provide the service root and evaluation key through the process environment:

```python
import os
from client.feature_flag_client import FeatureFlagClient

with FeatureFlagClient(os.environ["FEATURE_FLAG_BASE_URL"], os.environ["EVALUATION_API_KEY"]) as client:
    decision = client.evaluate("example-feature", "staging", "demo-user-001", groups=[])
```

Create/configure the example flag first. Set the base URL to `http://127.0.0.1:8000` locally or the deployed service root. The helper does not load `.env` automatically. It validates responses, uses a two-second default HTTPX timeout and no retries. Failures return `false` with `CLIENT_FALLBACK` and `fallback=true`, distinct from a valid server false. The timeout applies to network phases, not a guaranteed total deadline.

## Deployment

The demo uses Render + Neon PostgreSQL 18. Deploy a reviewed, clean `main` release after CI; keep `APPROVED_RELEASE_COMMIT` equal to that release's full SHA. Configure Python 3.12.15, Node 24.22.1, `APP_ENV=production`, private TLS `DATABASE_URL`, distinct admin/evaluation secrets, and automatic deployment off.

Current Render build command (normalizes provider-changed script modes before the strict guard):

```bash
chmod 644 scripts/ci/start_postgres.sh scripts/render/build.sh scripts/render/start.sh && bash scripts/render/build.sh
```

Start: `bash scripts/render/start.sh`. Health path: `/health/ready`. The service binds `0.0.0.0:$PORT`. `render.yaml` is a draft and omits the live permission workaround; do not apply it blindly. If committed script modes change, update the workaround in the same release.

Production migration is a separate authorized operation, not part of build/start. From the clean approved main checkout, temporarily provide production configuration, the expected direct Neon hostname/database and approved SHA through the environment—not the local development `.env`—then use:

```bash
python scripts/operations/release_guard.py --stage migrate --expected-host "$NEON_HOST" --expected-database "$NEON_DATABASE" --execute
```

The guard verifies the release/target, TLS and PostgreSQL 18. Do not seed production without separate approval. After deployment check `/`, `/health/live`, `/health/ready`, `/release.json` (approved SHA), unauthenticated API 401 and unknown API JSON 404; then perform an authorized synthetic workflow check. Readiness proves connectivity, not every business operation.

## Contributions and attribution

| Member | Workstream | Responsibilities / PR |
| --- | --- | --- |
| [Aguimmanuel](https://github.com/Aguimmanuel) | Flag API/data | Models, migrations, management and DB test safety — [PR #1](https://github.com/Aguimmanuel/23-feature-flag-service/pull/1). |
| [Fmichael01](https://github.com/Fmichael01) | Evaluation/client | Deterministic evaluator and Python helper — [PR #2](https://github.com/Aguimmanuel/23-feature-flag-service/pull/2). |
| [Oobiomah](https://github.com/Oobiomah) | Audit/integration | Transactional history, health, CI and deployment tooling — [PR #3](https://github.com/Aguimmanuel/23-feature-flag-service/pull/3). |
| [Wisdomjonathan-stack](https://github.com/Wisdomjonathan-stack) | Admin UI | Dashboard and frontend tests — [PR #6](https://github.com/Aguimmanuel/23-feature-flag-service/pull/6). |

Evaluation work is credited to Fmichael01; some repository authorship appears under `bibi6276` due to an account mismatch. Cross-component follow-up work is recorded in [PR #4](https://github.com/Aguimmanuel/23-feature-flag-service/pull/4) (backend/client hardening), [PR #7](https://github.com/Aguimmanuel/23-feature-flag-service/pull/7) (independent browser fixture) and [PR #8](https://github.com/Aguimmanuel/23-feature-flag-service/pull/8) (release). Workstream ownership does not imply sole authorship of these shared fixes.

Workflow: member branches from `develop` → reviewed PRs to `develop` → release PR to `main`; no direct main pushes. Each member should be able to explain their contribution and one technical decision.

Uses React, TypeScript, Vite, Vitest, Playwright, Testing Library, FastAPI, Pydantic, SQLAlchemy, psycopg, Alembic, HTTPX, Uvicorn and pytest under their upstream licences. Dependency resolution is recorded in `backend/requirements.txt` and `frontend/package-lock.json`. All four contributors used **Arena AI Agent** for code-generation assistance; contributors remain responsible for reviewing, testing and explaining submitted code. No commercial frontend template is bundled.

## Team retrospective

- **What worked:** a focused MVP, shared API/evaluation rules and real PostgreSQL tests supported integration across the four workstreams.
- **What caused rework:** inconsistent test credentials, tests depending on shared demo data, frontend/static-route interactions and provider script-permission changes.
- **What we would improve:** integrate a thin end-to-end flow earlier, use self-contained fixtures from the start, and test with the production frontend build present before release.

## Known limitations

Shared credentials are not individual accounts/RBAC; caller-supplied groups are trusted context. There is no configuration cache or automatic retry policy. Free hosting can sleep. Hosted load/cold starts, provider-restart persistence, backup/restore and rollback drills remain unverified. A warm local p95 of about 60 ms is not a hosted performance guarantee. Archive reserves keys; use a fresh demo key rather than resetting data.
