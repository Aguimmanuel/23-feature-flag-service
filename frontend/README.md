# Admin UI

React + TypeScript + Vite with plain CSS. This folder owns the frontend only: no backend implementation, database client, accounts, or external evaluation key.

## Local setup

Use the team's Node 24 baseline. No Python environment is needed to build or run component tests.

```bash
cd frontend
npm ci
npm run typecheck
npm test -- --run
npm run build
npm run dev -- --port 5173
```

Start FastAPI separately on port 8000. Browser code uses relative URLs; the Vite proxy forwards `/api` and `/health`. Without a backend, the UI reports real errors. It never substitutes fake successful decisions.

Enter the administrator token obtained privately from the team. It stays in React state and an API-client closure, never persistent storage or a URL. Refreshing the page or clearing the token signs you out. The first API request validates the token.

Restart Vite after reinstalling dependencies. If cached React modules return `504 (Outdated Optimize Dep)`, use `npm run dev -- --port 5173 --force`.

`allowedHosts: true` supports sandbox previews. Use the dev server only in trusted development environments; use a narrow allowlist if exposing it directly. Production does not run Vite's development server.

## Code tour

- `src/App.tsx`: named components for token entry, listing/creation, descriptions, environment configuration, tester, archival and audit.
- `src/api/types.ts`: snake_case API contract types.
- `src/api/client.ts`: centralized routes, bearer token, errors and runtime checks of unknown JSON. TypeScript alone cannot validate network payloads.
- `src/validation.ts`: identifier, group and integer-percentage validation. Identifiers are rejected rather than silently trimmed.
- `src/styles.css`: responsive plain CSS, visible focus outlines and explicit text for enabled/disabled states.
- `src/test/fixtures.ts`: synthetic component-test fixtures, never imported by release code.
- `src/App.test.tsx`, `src/api/client.test.ts`: component and network-boundary tests.
- `e2e/dashboard.spec.ts`: real-backend browser integration tests.

Configuration PUT submits every editable field plus the saved version. A VERSION_CONFLICT retains the user's input and offers explicit reload rather than silently retrying. The tester always calls the backend with saved environment settings, not unsaved editor values. Groups and percentage use OR; only the backend calculates decisions and buckets.

Changing flags/environments discards unsaved edits; the editor displays an unsaved warning. Reloading after a version conflict explicitly discards edits. A successful save resets the editor/tester to saved state.

## Real-backend browser tests

Use only an isolated local FastAPI/PostgreSQL 18 application, migrated and seeded with the original synthetic data. Start FastAPI on 8000 and Vite on 5173.

```bash
# Run once to install the Chromium browser and its system dependencies.
npx playwright install --with-deps chromium
```

Supply ADMIN_TOKEN privately through your terminal environment, not a committed file, VITE_* variable or command history. In Bash:

```bash
read -r -s -p 'Local admin token: ' ADMIN_TOKEN; echo
export ADMIN_TOKEN
npm run test:e2e
unset ADMIN_TOKEN
```

In VS Code PowerShell, a masked prompt can be used:

```powershell
$token = Read-Host 'Local admin token' -AsSecureString
$env:ADMIN_TOKEN = [System.Net.NetworkCredential]::new('', $token).Password
npm run test:e2e
Remove-Item Env:ADMIN_TOKEN
Remove-Variable token
```

Tests use real requests through the proxy, generate unique disposable flag names, and archive only their own flags afterward. They never truncate tables or reset the seeded flag. Do not run against the deployed demo. Browser traces and automatic screenshots are disabled; the deliberate screenshot is taken only after login with synthetic data.

`npm test -- --run` runs Vitest tests only; `npm run test:e2e` is a separate explicit command requiring the real backend. Type checking covers both suites. Coordinate adding the browser suite to CI with the deployment owner.

## Build handoff

Output is `frontend/dist/index.html` and `frontend/dist/assets/`. The backend/deployment owner serves this at the same origin, keeping API/health routes separate from SPA fallback. Do not commit dist, node_modules, local tokens or environment files. No secrets belong in VITE_* variables.

No docs/ folder is required to build or run this frontend. Browser screenshots are written to ignored test-results/evidence/.

Verified integration results: 15 component tests and five real-backend browser tests passed, along with type checking and the production build. Backend-owner caveat: with frontend/dist present, ten backend test-only probe cases are intercepted by the SPA fallback; without dist, all 287 backend tests pass. Actual API 401/409/404 behaviour passed browser tests. Coordinate the test-route ordering fix with the backend owners rather than hiding the failures.

## Attribution

Uses React, Vite, TypeScript, Vitest, Playwright and Testing Library under their upstream licences. Implementation prepared with AI coding assistance; review, understand and disclose that assistance according to course requirements. No commercial template or design system was copied.
