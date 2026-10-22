import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ApiError, createClient, type Client } from "./api/client";
import {
  environments,
  type Audit,
  type Configuration,
  type Decision,
  type Environment,
  type FlagDetail,
  type Page,
  type Flag,
} from "./api/types";
import { identifier, parseGroups, parsePercentage } from "./validation";
const message = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong. Please try again.";
function Notice({ text }: { text: string }) {
  return text ? (
    <p className="notice" role="alert">
      {text}
    </p>
  ) : null;
}

export default function App() {
  // Intentionally no localStorage/sessionStorage: a page refresh clears the token.
  const [token, setToken] = useState("");
  return (
    <>
      <header>
        <a className="brand" href="#main">
          ◈ Flagboard <span>ADMIN CONSOLE</span>
        </a>
        <span className="header-note">Feature control, without a redeploy</span>
      </header>
      <main id="main">
        {token ? (
          <Dashboard key={token} token={token} signOut={() => setToken("")} />
        ) : (
          <Login onLogin={setToken} />
        )}
      </main>
      <footer>
        Feature Flag Service · Environment-aware. Predictable by design.
      </footer>
    </>
  );
}
// Collect the token without saving it anywhere outside React state.
function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <section className="login panel">
      <p className="eyebrow">TEAM WORKSPACE</p>
      <h1>Control your next release.</h1>
      <p>
        Manage feature flags, test a user, and follow every configuration
        change.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (value) onLogin(value);
        }}
      >
        <label htmlFor="token">Administrator token</label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          required
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <button>Open dashboard →</button>
      </form>
      <p className="muted">
        Your token stays in memory only. Refreshing this page signs you out.
        Request access from your team lead.
      </p>
    </section>
  );
}
// The list and creation form share a refresh counter, not a global state library.
function Dashboard({ token, signOut }: { token: string; signOut: () => void }) {
  const api = useMemo(() => createClient(token), [token]);
  const [page, setPage] = useState<Page<Flag> | null>(null);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [unauthorized, setUnauthorized] = useState(false);
  const [key, setKey] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");
  useEffect(() => {
    // Ignore obsolete requests after page changes or unmounting.
    let current = true;
    setLoading(true);
    setError("");
    api
      .list(offset)
      .then((data) => {
        if (current) {
          setPage(data);
          setUnauthorized(false);
        }
      })
      .catch((e) => {
        if (current) {
          setError(message(e));
          setUnauthorized(e instanceof ApiError && e.status === 401);
        }
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [api, offset, revision]);
  async function create(e: FormEvent) {
    e.preventDefault();
    if (creating) return;
    setCreateError("");
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(key))
      return setCreateError(
        "Key must start with a lowercase letter and contain only lowercase letters, numbers, hyphens or underscores (maximum 64).",
      );
    if (description.length > 500)
      return setCreateError("Description must be at most 500 characters.");
    setCreating(true);
    try {
      const flag = await api.create(key, description);
      setSelected(flag.key);
      setKey("");
      setDescription("");
      setOffset(0);
      setRevision((r) => r + 1);
    } catch (e) {
      setCreateError(message(e));
    } finally {
      setCreating(false);
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">RELEASE MANAGEMENT</p>
          <h1>Feature flags</h1>
          <p className="muted">Small switches. Safer releases.</p>
        </div>
        <button className="secondary" onClick={signOut}>
          Clear token / sign out
        </button>
      </div>
      <div className="workspace">
        <aside>
          <section className="panel">
            <div className="section-heading">
              <h2>Active flags</h2>
              <button
                className="secondary small"
                disabled={loading}
                onClick={() => setRevision((r) => r + 1)}
              >
                Refresh
              </button>
            </div>
            {loading ? (
              <p role="status">Loading flags…</p>
            ) : error ? (
              <>
                <Notice text={error} />
                {unauthorized && (
                  <button onClick={signOut}>Re-enter token</button>
                )}
              </>
            ) : (
              <>
                {page?.items.length === 0 && (
                  <p>No active flags yet. Create your first flag below.</p>
                )}
                <ul className="flag-list">
                  {page?.items.map((f) => (
                    <li key={f.id}>
                      <button
                        className={
                          selected === f.key ? "flag selected" : "flag"
                        }
                        aria-pressed={selected === f.key}
                        onClick={() => setSelected(f.key)}
                      >
                        <strong>{f.key}</strong>
                        <span>{f.description || "No description"}</span>
                      </button>
                    </li>
                  ))}
                </ul>
                <div className="pagination">
                  <button
                    className="secondary small"
                    disabled={offset === 0}
                    onClick={() => setOffset((o) => Math.max(0, o - 50))}
                  >
                    Previous
                  </button>
                  <span>{page?.total ?? 0} flags</span>
                  <button
                    className="secondary small"
                    disabled={!page || offset + page.items.length >= page.total}
                    onClick={() => setOffset((o) => o + 50)}
                  >
                    Next
                  </button>
                </div>
              </>
            )}
          </section>
          <section className="panel">
            <h2>Create a flag</h2>
            <form onSubmit={create} noValidate>
              <label htmlFor="flag-key">Flag key</label>
              <input
                id="flag-key"
                placeholder="new-checkout"
                value={key}
                onChange={(e) => setKey(e.target.value)}
              />
              <label htmlFor="new-description">Description</label>
              <textarea
                id="new-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
              <Notice text={createError} />
              <button disabled={creating}>
                {creating ? "Creating…" : "+ Create flag"}
              </button>
            </form>
          </section>
        </aside>
        <div>
          {selected ? (
            <FlagWorkspace
              key={selected}
              flagKey={selected}
              api={api}
              onArchive={() => {
                setSelected("");
                setRevision((r) => r + 1);
              }}
              onChange={() => setRevision((r) => r + 1)}
            />
          ) : (
            <section className="panel empty">
              <span className="empty-symbol">⚑</span>
              <h2>A little control goes a long way.</h2>
              <p>
                Select a flag to configure its environments,
                <br />
                test a user, and inspect its history.
              </p>
            </section>
          )}
        </div>
      </div>
    </>
  );
}
// Load one selected flag; each environment editor gets its own form state.
function FlagWorkspace({
  flagKey,
  api,
  onArchive,
  onChange,
}: {
  flagKey: string;
  api: Client;
  onArchive: () => void;
  onChange: () => void;
}) {
  const [detail, setDetail] = useState<FlagDetail | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const [environment, setEnvironment] = useState<Environment>("development");
  const [auditRevision, setAuditRevision] = useState(0);
  const [feedback, setFeedback] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [archiveError, setArchiveError] = useState("");
  useEffect(() => {
    let current = true;
    setDetail(null);
    setError("");
    api
      .detail(flagKey)
      .then((d) => {
        if (current) setDetail(d);
      })
      .catch((e) => {
        if (current) setError(message(e));
      });
    return () => {
      current = false;
    };
  }, [api, flagKey, reload]);
  async function archive() {
    if (archiving) return;
    setArchiving(true);
    setArchiveError("");
    try {
      await api.archive(flagKey);
      onArchive();
    } catch (e) {
      setArchiveError(message(e));
    } finally {
      setArchiving(false);
    }
  }
  if (error)
    return (
      <section className="panel">
        <Notice text={error} />
        <button onClick={() => setReload((r) => r + 1)}>Retry detail</button>
      </section>
    );
  if (!detail)
    return (
      <section className="panel" role="status">
        Loading flag details…
      </section>
    );
  const configuration = detail.environments.find(
    (c) => c.environment === environment,
  )!;
  return (
    <>
      <section className="panel">
        <p className="eyebrow">FLAG CONFIGURATION</p>
        <div className="section-heading">
          <h2>{detail.key}</h2>
          <span className="badge">Boolean flag</span>
        </div>
        <DescriptionEditor
          key={detail.updated_at}
          initial={detail.description}
          api={api}
          flagKey={flagKey}
          onSaved={(d) => {
            setDetail(d);
            setAuditRevision((r) => r + 1);
            onChange();
          }}
        />
        <label htmlFor="environment">Environment</label>
        <select
          id="environment"
          value={environment}
          onChange={(e) => setEnvironment(e.target.value as Environment)}
        >
          {environments.map((env) => (
            <option key={env}>{env}</option>
          ))}
        </select>
        <p role="status" className="help">
          {feedback}
        </p>
        <ConfigEditor
          key={`${environment}-${configuration.version}`}
          configuration={configuration}
          flagKey={flagKey}
          api={api}
          onSaved={(saved) => {
            setFeedback(
              `Configuration saved for ${saved.environment} (version ${saved.version}).`,
            );
            setDetail(
              (d) =>
                d && {
                  ...d,
                  environments: d.environments.map((c) =>
                    c.environment === saved.environment ? saved : c,
                  ),
                },
            );
            setAuditRevision((r) => r + 1);
            onChange();
          }}
          onReload={() => setReload((r) => r + 1)}
        />
        <hr />
        <button className="danger secondary" onClick={() => setConfirm(true)}>
          Archive flag…
        </button>
        {confirm && (
          <div
            className="confirmation"
            role="group"
            aria-label="Confirm archival"
          >
            <p>
              Archive <strong>{flagKey}</strong>? It will stop evaluating and
              leave the active list. Its key stays reserved; audit history
              remains available through the API.
            </p>
            <Notice text={archiveError} />
            <button className="danger" disabled={archiving} onClick={archive}>
              {archiving ? "Archiving…" : "Confirm archive"}
            </button>{" "}
            <button
              className="secondary"
              disabled={archiving}
              onClick={() => setConfirm(false)}
            >
              Cancel
            </button>
          </div>
        )}
      </section>
      <AuditHistory api={api} flagKey={flagKey} revision={auditRevision} />
    </>
  );
}
// Description updates use PATCH and are separate from versioned configurations.
function DescriptionEditor({
  initial,
  api,
  flagKey,
  onSaved,
}: {
  initial: string;
  api: Client;
  flagKey: string;
  onSaved: (d: FlagDetail) => void;
}) {
  const [value, setValue] = useState(initial);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        if (pending) return;
        setError("");
        if (value.length > 500)
          return setError("Description must be at most 500 characters.");
        setPending(true);
        try {
          onSaved(await api.describe(flagKey, value));
        } catch (e) {
          setError(message(e));
        } finally {
          setPending(false);
        }
      }}
    >
      <label htmlFor="description">Flag description</label>
      <textarea
        id="description"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <Notice text={error} />
      <button
        className="secondary small"
        disabled={pending || value === initial}
      >
        {pending ? "Saving description…" : "Save description"}
      </button>
    </form>
  );
}
// Keep editable fields separate from the saved configuration and submit its version.
function ConfigEditor({
  configuration: c,
  flagKey,
  api,
  onSaved,
  onReload,
}: {
  configuration: Configuration;
  flagKey: string;
  api: Client;
  onSaved: (c: Configuration) => void;
  onReload: () => void;
}) {
  const [enabled, setEnabled] = useState(c.enabled);
  const [groups, setGroups] = useState(c.target_groups.join("\n"));
  const [percentage, setPercentage] = useState(String(c.rollout_percentage));
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [saved, setSaved] = useState(false);
  const dirty =
    enabled !== c.enabled ||
    groups !== c.target_groups.join("\n") ||
    percentage !== String(c.rollout_percentage);
  async function save(e: FormEvent) {
    e.preventDefault();
    if (pending) return;
    setError("");
    setSaved(false);
    let target_groups: string[], rollout_percentage: number;
    try {
      target_groups = parseGroups(groups);
      rollout_percentage = parsePercentage(percentage);
    } catch (e) {
      setError(message(e));
      return;
    }
    setPending(true);
    try {
      const next = await api.save(flagKey, c.environment, {
        enabled,
        target_groups,
        rollout_percentage,
        version: c.version,
      });
      onSaved(next);
      setSaved(true);
    } catch (e) {
      setError(message(e));
      setConflict(e instanceof ApiError && e.code === "VERSION_CONFLICT");
    } finally {
      setPending(false);
    }
  }
  return (
    <>
      <form onSubmit={save} noValidate>
        <div className="switch-row">
          <label htmlFor="enabled">
            <input
              id="enabled"
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />{" "}
            Feature {enabled ? "enabled" : "disabled"}
          </label>
          <span className="badge">Version {c.version}</span>
        </div>
        <label htmlFor="target-groups">Target groups</label>
        <textarea
          id="target-groups"
          aria-describedby="group-help"
          value={groups}
          onChange={(e) => setGroups(e.target.value)}
        />
        <p id="group-help" className="help">
          One exact, case-sensitive group per line. Matching groups OR
          percentage rollout are included.
        </p>
        <label htmlFor="rollout">Rollout percentage</label>
        <div className="percentage">
          <input
            id="rollout"
            type="number"
            min="0"
            max="100"
            step="1"
            value={percentage}
            onChange={(e) => setPercentage(e.target.value)}
          />
          <span>% of other users</span>
        </div>
        <p className="help">
          The master disabled switch overrides every inclusion path.
        </p>
        <p role="status" className={dirty ? "unsaved" : "muted"}>
          {dirty
            ? "Unsaved changes — the tester still uses saved settings."
            : saved
              ? "Configuration saved."
              : "Showing saved configuration."}
        </p>
        <Notice text={error} />
        {conflict && (
          <p>
            <button type="button" className="secondary" onClick={onReload}>
              Reload latest configuration
            </button>{" "}
            <span className="help">Reload discards these unsaved edits.</span>
          </p>
        )}
        <button disabled={pending || conflict}>
          {pending ? "Saving…" : "Save configuration"}
        </button>
      </form>
      <Tester
        api={api}
        flagKey={flagKey}
        environment={c.environment}
        dirty={dirty}
      />
    </>
  );
}
// Call the admin endpoint. Errors are not feature-disabled decisions.
function Tester({
  api,
  flagKey,
  environment,
  dirty,
}: {
  api: Client;
  flagKey: string;
  environment: Environment;
  dirty: boolean;
}) {
  const [id, setId] = useState("");
  const [groups, setGroups] = useState("");
  const [result, setResult] = useState<Decision | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  // Changing the context invalidates an earlier decision; never show it as current.
  const generation = useRef(0);
  useEffect(() => {
    generation.current++;
    setResult(null);
  }, [id, groups]);
  return (
    <section className="tester">
      <h3>User evaluation tester</h3>
      <p className="help">
        Uses saved {environment} settings.
        {dirty && " Save your edits to test their effect."}
      </p>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          if (pending) return;
          setError("");
          setResult(null);
          let parsed: string[];
          try {
            if (!identifier(id, 128))
              throw new Error(
                "User ID must be 1–128 characters without surrounding whitespace or control characters.",
              );
            parsed = parseGroups(groups);
          } catch (e) {
            setError(message(e));
            return;
          }
          const requestGeneration = generation.current;
          setPending(true);
          try {
            const decision = await api.evaluate(
              flagKey,
              environment,
              id,
              parsed,
            );
            if (requestGeneration === generation.current) {
              if (
                decision.flag_key !== flagKey ||
                decision.environment !== environment
              )
                throw new Error(
                  "Evaluation response context does not match the request.",
                );
              setResult(decision);
            }
          } catch (e) {
            setError(message(e));
          } finally {
            setPending(false);
          }
        }}
        noValidate
      >
        <label htmlFor="user-id">Synthetic user ID</label>
        <input
          id="user-id"
          placeholder="user-003"
          value={id}
          onChange={(e) => setId(e.target.value)}
        />
        <label htmlFor="user-groups">User groups (one per line)</label>
        <textarea
          id="user-groups"
          value={groups}
          onChange={(e) => setGroups(e.target.value)}
        />
        <button className="secondary" disabled={pending}>
          {pending ? "Evaluating…" : "Evaluate user"}
        </button>
        <Notice text={error} />
        {result && (
          <div className="result" role="status">
            <strong>
              {result.value ? "Enabled · true" : "Disabled · false"}
            </strong>
            <span>{result.reason}</span>
            <small>Bucket: {result.bucket ?? "Not used"}</small>
          </div>
        )}
      </form>
    </section>
  );
}
// Audit history is read-only and paginated; never fabricate events in the browser.
function AuditHistory({
  api,
  flagKey,
  revision,
}: {
  api: Client;
  flagKey: string;
  revision: number;
}) {
  const [page, setPage] = useState<Page<Audit> | null>(null);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setLoading(true);
    setError("");
    api
      .audit(flagKey, offset)
      .then((p) => {
        if (current) setPage(p);
      })
      .catch((e) => {
        if (current) setError(message(e));
      })
      .finally(() => {
        if (current) setLoading(false);
      });
    return () => {
      current = false;
    };
  }, [api, flagKey, revision, offset, retry]);
  return (
    <section className="panel">
      <p className="eyebrow">CHANGE RECORD</p>
      <div className="section-heading">
        <h2>Audit history</h2>
        <button
          className="secondary small"
          disabled={loading}
          onClick={() => {
            setOffset(0);
            setRetry((r) => r + 1);
          }}
        >
          Refresh history
        </button>
      </div>
      {loading ? (
        <p role="status">Loading history…</p>
      ) : error ? (
        <Notice text={error} />
      ) : (
        <>
          {!page?.items.length && <p>No changes recorded.</p>}
          <ul className="audit-list">
            {page?.items.map((a) => (
              <li key={a.id}>
                <strong>{a.action.replaceAll("_", " ")}</strong>
                <p className="help">
                  {a.environment ?? "Flag"} · {a.actor} ·{" "}
                  {new Date(a.created_at).toLocaleString()}
                </p>
                <details>
                  <summary>Before / after</summary>
                  <pre>
                    {JSON.stringify(
                      { before: a.before, after: a.after },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </li>
            ))}
          </ul>
          <div className="pagination">
            <button
              className="secondary small"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - 50))}
            >
              Earlier page
            </button>
            <span>{page?.total ?? 0} changes</span>
            <button
              className="secondary small"
              disabled={!page || offset + page.items.length >= page.total}
              onClick={() => setOffset((o) => o + 50)}
            >
              Older changes
            </button>
          </div>
        </>
      )}
    </section>
  );
}
