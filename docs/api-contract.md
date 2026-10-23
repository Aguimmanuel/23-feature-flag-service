# API Contract

Business routes use `/api/v1`. Send JSON bodies with `Content-Type: application/json`. Responses use snake_case fields; timestamps are UTC ISO 8601 strings and UUIDs are strings. See `/docs` or `/openapi.json` on a running backend for complete schemas.

## Authentication

- Management, audit and admin preview: `Authorization: Bearer <ADMIN_TOKEN>`.
- External evaluation: `X-API-Key: <EVALUATION_API_KEY>`.
- These credentials are distinct. Missing or incorrect credentials return 401. Never put either secret in a URL or publish them in examples.

## Endpoints

| Method and full path | Purpose / successful response |
| --- | --- |
| `POST /api/v1/flags` | Create flag and three disabled configurations; **201** flag detail and `Location` header. |
| `GET /api/v1/flags` | **200** active flag summaries, key ascending. |
| `GET /api/v1/flags/{key}` | **200** flag detail with `environments`. |
| `PATCH /api/v1/flags/{key}` | Update description only; **200** flag detail. |
| `PUT /api/v1/flags/{key}/environments/{environment}` | Save complete configuration with current version; **200** updated configuration. |
| `DELETE /api/v1/flags/{key}` | Archive, retain history and reserve key; **204**, no body. |
| `GET /api/v1/flags/{key}/audit` | **200** audit history, including archived flags; newest first. |
| `POST /api/v1/admin/evaluate` | **200** saved-state evaluation using admin credential. |
| `POST /api/v1/evaluate` | **200** same evaluation using evaluation-only credential. |

List and audit responses use `{"items":[],"total":0,"limit":50,"offset":0}`. Both accept `limit` (1–100, default 50) and `offset` (nonnegative, default 0).

## Request examples

Create:

```json
{"key":"example-feature","description":"Synthetic release example"}
```

Save staging with PUT to `/api/v1/flags/example-feature/environments/staging`:

```json
{"enabled":true,"target_groups":["beta"],"rollout_percentage":25,"version":1}
```

A successful first save returns the updated configuration, for example:

```json
{
  "environment": "staging",
  "enabled": true,
  "target_groups": ["beta"],
  "rollout_percentage": 25,
  "version": 2,
  "updated_at": "2026-10-22T12:00:00Z"
}
```

PUT requires all four request fields; omitted fields are not left unchanged. Only the selected environment changes. Use the version returned by the latest detail/save response—not always `1`. Successful saves increment it. A stale save returns 409 without changing configuration or adding an audit event. On 409, fetch the latest configuration, review the differences and explicitly save again; do not blindly retry. Description PATCH takes only `description` and does not use this version check.

Evaluate using either evaluation route:

```json
{"flag_key":"example-feature","environment":"staging","user":{"id":"demo-user-001","groups":["beta"]}}
```

With the saved configuration above:

```json
{"flag_key":"example-feature","environment":"staging","value":true,"reason":"GROUP_MATCH","bucket":null}
```

These are examples, not pre-existing hosted records. A detail response contains the flag's `id`, `key`, `description`, `archived`, timestamps and three environment configurations. Configuration responses include `environment`, `enabled`, `target_groups`, `rollout_percentage`, `version` and `updated_at`.

## Validation and evaluation

- Key: `^[a-z][a-z0-9_-]{0,63}$`; immutable and unique, including archived keys. Description: at most 500 characters.
- Environment: `development`, `staging` or `production`.
- User ID: 1–128 characters. Group: 1–64 characters. Neither accepts surrounding whitespace or ASCII controls.
- Groups: at most 20 unique, case-sensitive names; target groups are saved sorted. Evaluation groups default to `[]`.
- Enabled must be a real boolean; percentage a real integer 0–100; version a real integer ≥1. Unknown body fields are rejected. JSON bodies are limited to 32 KiB.

Evaluation order: missing/archived flag → 404; missing configuration → 404; disabled → `FLAG_DISABLED`; matching group → `GROUP_MATCH`; otherwise percentage → `ROLLOUT_INCLUDED` or `ROLLOUT_EXCLUDED`.

| Decision reason | Value | Meaning |
| --- | --- | --- |
| `FLAG_DISABLED` | `false` | Master switch is off, regardless of groups or rollout. |
| `GROUP_MATCH` | `true` | At least one supplied group matches a target group, even at 0%. |
| `ROLLOUT_INCLUDED` | `true` | No group match; user's bucket is below the threshold. |
| `ROLLOUT_EXCLUDED` | `false` | No group match; user's bucket is at or above the threshold. |

For percentage rollout, SHA-256 the UTF-8 string `flag_key:user.id`, take the first eight hexadecimal characters, convert to an integer, then modulo 10,000. Include when `bucket < percentage * 100`. `bucket` is null for disabled/group decisions and 0–9999 for percentage decisions. The same flag/user pair keeps its bucket across requests and environments; 25% means a threshold of 2500, not exactly 25 users out of every 100. Evaluation reads saved settings without a cache and does not write audit events. Caller-supplied groups are not independently verified memberships.

## Audit and errors

Audit items contain `id`, `flag_key`, `environment`, `action`, `actor`, `before`, `after` and `created_at`. Actions are `FLAG_CREATED`, `FLAG_UPDATED`, `CONFIG_UPDATED` and `FLAG_ARCHIVED`. Flag-level actions have null environment; creation has null `before`. Runtime actor is `shared-admin`, not an individual account. For `CONFIG_UPDATED`, snapshots contain `enabled`, `target_groups`, `rollout_percentage` and `version`; flag-level snapshots contain `key`, `description` and `archived`. There are no audit-edit/delete routes.

Errors use one envelope; validation details contain sanitized field names/messages:

```json
{"error":{"code":"VERSION_CONFLICT","message":"Configuration version is stale; reload before saving","details":[]}}
```

| HTTP | Codes / meaning |
| --- | --- |
| 401 | `UNAUTHORIZED` — missing/incorrect credential. |
| 404 | `FLAG_NOT_FOUND`, `ENVIRONMENT_CONFIG_NOT_FOUND`; unknown API/health routes use `HTTP_ERROR`. |
| 405 | `HTTP_ERROR` — method not supported for the route. |
| 409 | `FLAG_KEY_CONFLICT` or `VERSION_CONFLICT`. |
| 413 / 422 | `PAYLOAD_TOO_LARGE` / `VALIDATION_ERROR`. |
| 500 / 503 | `INTERNAL_ERROR` / `SERVICE_UNAVAILABLE`; sanitized server/database errors. |

Public health routes: `GET /health/live` → `{"status":"ok"}`; `GET /health/ready` → `{"status":"ready"}` or 503. Readiness checks database connectivity, not every workflow.

The [Python helper](../client/feature_flag_client.py) validates successful responses. On service/network errors or malformed results it returns `value=false`, `reason="CLIENT_FALLBACK"`, `fallback=true`; a legitimate server false has `fallback=false`. The API itself does not turn failures into successful false decisions. See the [README](../README.md) for setup and helper usage.
