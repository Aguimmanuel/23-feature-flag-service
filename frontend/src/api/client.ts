import {
  environments,
  type Flag,
  type FlagDetail,
  type Configuration,
  type Page,
  type Decision,
  type Audit,
  type Environment,
  type ConfigInput,
} from "./types";
// Network data is unknown until checked. Types alone cannot protect the UI.
type Guard<T> = (value: unknown) => value is T;
const object = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const integer = (v: unknown): v is number =>
  typeof v === "number" && Number.isInteger(v);
const env = (v: unknown): v is Environment =>
  environments.includes(v as Environment);
const strings = (v: unknown): v is string[] =>
  Array.isArray(v) && v.every((x) => typeof x === "string");
const flag: Guard<Flag> = (v): v is Flag =>
  object(v) &&
  ["id", "key", "description", "created_at", "updated_at"].every(
    (k) => typeof v[k] === "string",
  ) &&
  typeof v.archived === "boolean";
const config: Guard<Configuration> = (v): v is Configuration =>
  object(v) &&
  env(v.environment) &&
  typeof v.enabled === "boolean" &&
  strings(v.target_groups) &&
  integer(v.rollout_percentage) &&
  v.rollout_percentage >= 0 &&
  v.rollout_percentage <= 100 &&
  integer(v.version) &&
  v.version >= 1 &&
  typeof v.updated_at === "string";
const detail: Guard<FlagDetail> = (v): v is FlagDetail =>
  flag(v) &&
  object(v) &&
  Array.isArray(v.environments) &&
  v.environments.length === 3 &&
  v.environments.every(config) &&
  environments.every(
    (e) =>
      (v.environments as Configuration[]).filter((c) => c.environment === e)
        .length === 1,
  );
const decision: Guard<Decision> = (v): v is Decision => {
  if (
    !object(v) ||
    typeof v.flag_key !== "string" ||
    !env(v.environment) ||
    typeof v.value !== "boolean"
  )
    return false;
  if (v.reason === "FLAG_DISABLED")
    return v.value === false && v.bucket === null;
  if (v.reason === "GROUP_MATCH") return v.value === true && v.bucket === null;
  return (
    (v.reason === "ROLLOUT_INCLUDED" || v.reason === "ROLLOUT_EXCLUDED") &&
    v.value === (v.reason === "ROLLOUT_INCLUDED") &&
    integer(v.bucket) &&
    v.bucket >= 0 &&
    v.bucket <= 9999
  );
};
const audit: Guard<Audit> = (v): v is Audit =>
  object(v) &&
  ["id", "flag_key", "actor", "created_at"].every(
    (k) => typeof v[k] === "string",
  ) &&
  ["FLAG_CREATED", "FLAG_UPDATED", "CONFIG_UPDATED", "FLAG_ARCHIVED"].includes(
    v.action as string,
  ) &&
  (v.environment === null || env(v.environment)) &&
  (v.before === null || object(v.before)) &&
  object(v.after);
const page =
  <T>(check: Guard<T>): Guard<Page<T>> =>
  (v): v is Page<T> =>
    object(v) &&
    Array.isArray(v.items) &&
    v.items.every(check) &&
    integer(v.total) &&
    v.total >= 0 &&
    integer(v.limit) &&
    v.limit >= 1 &&
    integer(v.offset) &&
    v.offset >= 0;
export class ApiError extends Error {
  constructor(
    message: string,
    public code = "REQUEST_FAILED",
    public status = 0,
  ) {
    super(message);
  }
}
// The token lives in this closure only; never persist it or put it in a URL.
export function createClient(token: string) {
  async function request<T>(
    path: string,
    check: Guard<T>,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`/api/v1${path}`, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      throw new ApiError(
        "Cannot reach the service. Check your connection and try again.",
      );
    }
    if (response.status === 204 && method === "DELETE") return undefined as T;
    let data: unknown;
    try {
      data = await response.json();
    } catch {
      throw new ApiError(
        "The service returned an unexpected response.",
        "INVALID_RESPONSE",
        response.status,
      );
    }
    if (!response.ok) {
      // Show only documented messages/field errors, never raw response text or headers.
      if (
        object(data) &&
        object(data.error) &&
        typeof data.error.message === "string" &&
        typeof data.error.code === "string"
      ) {
        const fields = Array.isArray(data.error.details)
          ? data.error.details
              .filter(object)
              .map((d) =>
                typeof d.field === "string" && typeof d.message === "string"
                  ? `${d.field}: ${d.message}`
                  : "",
              )
              .filter(Boolean)
              .join("; ")
          : "";
        throw new ApiError(
          `${data.error.message}${fields ? ` — ${fields}` : ""}`,
          data.error.code,
          response.status,
        );
      }
      throw new ApiError(
        response.status === 401
          ? "Administrator token was rejected. Re-enter your token."
          : `Request failed (${response.status}).`,
        "REQUEST_FAILED",
        response.status,
      );
    }
    if (!check(data))
      throw new ApiError(
        "The service response does not match the API contract.",
        "INVALID_RESPONSE",
      );
    return data;
  }
  const keyPath = (key: string) => `/flags/${encodeURIComponent(key)}`;
  return {
    list: (offset = 0) =>
      request("/flags?limit=50&offset=" + offset, page(flag)),
    create: (key: string, description: string) =>
      request("/flags", detail, "POST", { key, description }),
    detail: (key: string) => request(keyPath(key), detail),
    save: (key: string, environment: Environment, input: ConfigInput) =>
      request(
        `${keyPath(key)}/environments/${environment}`,
        config,
        "PUT",
        input,
      ),
    describe: (key: string, description: string) =>
      request(keyPath(key), detail, "PATCH", { description }),
    archive: (key: string) =>
      request(keyPath(key), (_): _ is undefined => false, "DELETE"),
    audit: (key: string, offset = 0) =>
      request(`${keyPath(key)}/audit?limit=50&offset=${offset}`, page(audit)),
    evaluate: (
      flag_key: string,
      environment: Environment,
      id: string,
      groups: string[],
    ) =>
      request("/admin/evaluate", decision, "POST", {
        flag_key,
        environment,
        user: { id, groups },
      }),
  };
}
export type Client = ReturnType<typeof createClient>;
