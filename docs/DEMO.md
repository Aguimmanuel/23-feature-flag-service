# Flagboard Demo and Manual Checks

Open https://flagboard-service.onrender.com/ or the local app from the [README](../README.md). Sign in with the admin token privately. Use synthetic data and a fresh flag key, such as `demo-checkout-01`; use a new suffix if it already exists or was archived.

These are actions and expected results, **not a record that every check has passed**. Use only your own demo flags. The core flow is below; additional checks cover different behaviours without repeating that flow.

## Core flow

| Step | Action | Expected result |
| --- | --- | --- |
| 1. Create | Create the flag and select **staging**. | All three environments start disabled, with empty target groups and 0% rollout. |
| 2. Group targeting | Enable staging, set target groups to `beta`, rollout to **0%**, and save. Evaluate user `demo-user-001` with group `beta`. | `true` — `GROUP_MATCH`; bucket is not used. |
| 3. Zero rollout | Clear the user's groups and evaluate again. | `false` — `ROLLOUT_EXCLUDED`. |
| 4. Full rollout | Set rollout to **100%**, save, and evaluate the same user without groups. | `true` — `ROLLOUT_INCLUDED`. |
| 5. Disabled override | Disable the flag, save, and evaluate with group `beta`. | `false` — `FLAG_DISABLED`, despite the matching group and 100% rollout. |
| 6. History and persistence | View audit history, then refresh and sign in privately again. Reopen the flag in staging. | Staging is still disabled at 100%; history includes creation and configuration changes. |

Save before evaluating; re-enter tester fields if saving clears them. Refreshing clears the in-memory token, not the database records. A consuming application must use the returned boolean to show or hide its own feature.

## Additional dashboard checks

Each row states its own setup. Enter multiple groups **one per line**, not comma-separated. Run archival last; leave any remaining demo flags disabled.

### Targeting and saved state

| Check | Action | Expected result |
| --- | --- | --- |
| T1. Case sensitivity | Save enabled, target `beta`, 0%. Evaluate with group `Beta`. | `false` — `ROLLOUT_EXCLUDED`; case matters. |
| T2. Any matching group | Save enabled, targets `beta` and `staff`, 0%. Evaluate with groups `guest` and `staff`. | `true` — `GROUP_MATCH`; not all groups need to match. |
| T3. No configured groups | Save enabled, empty target groups, 0%. Evaluate with group `beta`. | `false`; a supplied group alone does not grant access. |
| T4. Stable intermediate rollout | Save enabled, no targets, 25%. Evaluate the same user twice without changing saved settings. | Same bucket, boolean and reason both times. Below 2500 means included; otherwise excluded. No need to search for a particular bucket. |
| T5. Environment isolation | Save staging enabled at 100%; leave production at its original disabled/0%. Evaluate the same user without groups in each. | Staging: `true`; production: `FLAG_DISABLED`. Changing staging did not change production. |
| T6. Unsaved changes | Save enabled, no targets, 100%. Change the editor to 0% **without saving**, then evaluate without groups. | Unsaved warning; result remains `true` using saved 100%. |
| T7. Discarded edits | Change a saved value without saving, switch environment, then return. | Saved values return; unsaved edits were not persisted. |

### Validation, editing and usability

| Check | Action | Expected result |
| --- | --- | --- |
| T8. Invalid flag identity | Try a key with uppercase letters, spaces or a leading digit; also try a description longer than 500 characters. | Invalid input is rejected; no flag is created. |
| T9. Duplicate identity | Try creating the existing demo key again. | Conflict error; original flag remains unchanged and entered form values are retained. |
| T10. Invalid rollout | Try -1, 101 and 25.5, then save. | Rejected; saved percentage stays unchanged. |
| T11. Invalid groups | Try duplicate lines, a whitespace-padded name, or more than 20 groups in the configuration/tester. | Validation error; no invalid save or successful decision. An entirely empty group field is valid. |
| T12. Invalid user ID | Evaluate with an empty or whitespace-padded ID, including while the flag is disabled. | Validation error, not a successful `FLAG_DISABLED` response. |
| T13. Description update | Save a new synthetic description, reopen the flag and inspect history. | Description persists; `FLAG_UPDATED` contains before/after descriptions. |
| T14. Stale save | Open the same configuration in two tabs. Save a change in tab A, then a different change from the old copy in tab B. | Tab B gets a version conflict and keeps its edits. **Reload latest configuration** loads A's saved values instead of overwriting them. |
| T15. Invalid login | Sign out, enter a deliberately invalid token, and open the dashboard. | Protected data does not load; an authentication error appears. Sign in privately with the correct token afterward. |
| T16. Narrow screen | Use a mobile-width viewport and access the list, editor, tester and history. | Controls remain usable without page-level horizontal scrolling. |

### Audit and lifecycle

| Check | Action | Expected result |
| --- | --- | --- |
| T17. Read-only evaluation | Note the audit count, evaluate repeatedly, then **Refresh history** without saving. | No new audit entries; evaluation is read-only. |
| T18. Rejected changes | Note the version/history count, attempt an invalid save or a stale save, then reload saved state/history. | No rejected change, version increment or audit event is committed. |
| T19. Snapshot accuracy | Save one valid configuration change and open its **Before / after** entry. | Old/new fields and incremented version match the change; newest event appears first. |
| T20. Cancel archival | Open **Archive flag…**, then **Cancel**. | Flag stays active and no archival event is added. |
| T21. Confirm archival — last | Confirm archive on your own demo flag, refresh the active list, then try creating the same key again. | Flag leaves the active list; the key remains reserved. Retained history can be checked through the API below. |

## Optional API checks

Use a local API client or the local backend's `/docs`; see the [API contract](api-contract.md) for bodies and credentials. Use the same synthetic flag before archival, except A9. Keep credentials out of URLs, captures and saved request exports. UI validation and API validation are separate boundaries.

| Check | Action | Expected result |
| --- | --- | --- |
| A1. Credential separation | Send a valid evaluation request with the evaluation key, then try management with that key or external evaluation with only the admin Bearer token. | Evaluation-only access works; wrong/missing credential type returns 401. |
| A2. Strict JSON | With valid auth, PUT `enabled:"true"`, `rollout_percentage:"25"` or an extra unknown field, one invalid case at a time. | 422 `VALIDATION_ERROR`; no mutation. |
| A3. Complete PUT | Omit `version` or another required configuration field. | 422; PUT is not a partial update. |
| A4. Invalid environment | Request a configuration using environment `qa`. | 422, not an automatically created environment. |
| A5. Missing flag | Evaluate a validly formatted fresh key that does not exist. | 404 `FLAG_NOT_FOUND`, not HTTP 200 with `false`. |
| A6. Pagination | List flags with `limit=1&offset=0`, then offset 1; also try `limit=0`. | Correct page envelopes and key order; second page may be empty; invalid limit returns 422. |
| A7. Unknown route | GET `/api/v1/not-a-route` without sending credentials. | JSON 404 `HTTP_ERROR`, not the frontend HTML page. |
| A8. Health | GET `/health/live` and `/health/ready` on a healthy running app. | 200 `status:ok` and `status:ready`. Readiness checks DB connectivity only. |
| A9. Archived access | After T21, evaluate/get the archived flag, then GET `/api/v1/flags/{key}/audit` with admin auth. | Flag detail/evaluation return 404; history remains available and includes `FLAG_ARCHIVED`. |

Do not create outages, corrupt records, reset databases or run destructive integration tests against the hosted service. Audit-failure rollback, exact hash boundaries and client-fallback cases are covered by the local automated suites described in the README, rather than by damaging a live demo.
