import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";
import { empty, evaluation, errorBody, flag, list } from "./test/fixtures";
const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
function mockApi(
  custom?: (
    url: string,
    init?: RequestInit,
  ) => Response | Promise<Response> | undefined,
) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const override = custom?.(url, init);
    if (override) return Promise.resolve(override);
    if (url.includes("/audit")) return Promise.resolve(json(empty));
    if (url.includes("/flags?")) return Promise.resolve(json(list));
    if (url.endsWith("/admin/evaluate"))
      return Promise.resolve(json(evaluation));
    return Promise.resolve(json(flag));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
async function login() {
  const user = userEvent.setup();
  await user.type(
    screen.getByLabelText("Administrator token"),
    "synthetic-test-token",
  );
  await user.click(screen.getByRole("button", { name: /Open dashboard/ }));
  return user;
}
async function selectFlag(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /new-checkout/ }));
  await screen.findByLabelText("Environment");
}
describe("Frontend dashboard", () => {
  it("shows loading then empty state; keyboard login; token only lives until remount", async () => {
    let resolve!: (r: Response) => void;
    mockApi((url) =>
      url.includes("/flags?")
        ? new Promise((r) => {
            resolve = r;
          })
        : undefined,
    );
    const view = render(<App />);
    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Administrator token"));
    await user.type(screen.getByLabelText("Administrator token"), "synthetic");
    await user.keyboard("{Enter}");
    expect(screen.getByText("Loading flags…")).toBeInTheDocument();
    resolve(json(empty));
    expect(await screen.findByText(/No active flags yet/)).toBeInTheDocument();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    view.unmount();
    render(<App />);
    expect(screen.getByLabelText("Administrator token")).toHaveValue("");
  });
  it("shows unauthorized and allows token re-entry", async () => {
    mockApi(() => json(errorBody("UNAUTHORIZED", "Token rejected"), 401));
    render(<App />);
    const user = await login();
    await user.click(
      await screen.findByRole("button", { name: "Re-enter token" }),
    );
    expect(screen.getByLabelText("Administrator token")).toHaveValue("");
  });
  it("shows network errors without rendering fake flags", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("offline")));
    render(<App />);
    await login();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot reach the service",
    );
    expect(
      screen.queryByRole("button", { name: /new-checkout/ }),
    ).not.toBeInTheDocument();
  });
  it("validates creation and retains inputs on server failure", async () => {
    mockApi((url, init) =>
      url.endsWith("/flags") && init?.method === "POST"
        ? json(errorBody("FLAG_KEY_CONFLICT", "Key already exists"), 409)
        : undefined,
    );
    render(<App />);
    const user = await login();
    await user.type(screen.getByLabelText("Flag key"), "Bad key");
    await user.click(screen.getByRole("button", { name: "+ Create flag" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Key must start");
    await user.clear(screen.getByLabelText("Flag key"));
    await user.type(screen.getByLabelText("Flag key"), "new-checkout");
    await user.type(
      screen.getByLabelText("Description", { exact: true }),
      "Keep this",
    );
    await user.click(screen.getByRole("button", { name: "+ Create flag" }));
    expect(await screen.findByText("Key already exists")).toBeInTheDocument();
    expect(screen.getByLabelText("Description", { exact: true })).toHaveValue(
      "Keep this",
    );
  });
  it("prevents repeated creation while pending", async () => {
    let resolve!: (r: Response) => void;
    const fetcher = mockApi((url, init) =>
      url.endsWith("/flags") && init?.method === "POST"
        ? new Promise((r) => {
            resolve = r;
          })
        : undefined,
    );
    render(<App />);
    const user = await login();
    await user.type(screen.getByLabelText("Flag key"), "new-checkout");
    await user.click(screen.getByRole("button", { name: "+ Create flag" }));
    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    resolve(json(flag, 201));
    await screen.findByLabelText("Environment");
    expect(
      fetcher.mock.calls.filter(
        ([url, init]) => url.endsWith("/flags") && init?.method === "POST",
      ),
    ).toHaveLength(1);
  });
  it("sends complete configuration; retains edits on conflict and offers explicit reload", async () => {
    const fetcher = mockApi((url, init) =>
      init?.method === "PUT"
        ? json(errorBody("VERSION_CONFLICT", "A newer version exists"), 409)
        : undefined,
    );
    render(<App />);
    const user = await login();
    await selectFlag(user);
    expect(screen.getByLabelText("Feature disabled")).not.toBeChecked();
    await user.click(screen.getByLabelText("Feature disabled"));
    await user.type(screen.getByLabelText("Target groups"), "beta");
    await user.clear(screen.getByLabelText("Rollout percentage"));
    await user.type(screen.getByLabelText("Rollout percentage"), "25");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Save configuration" }),
    );
    expect(
      await screen.findByRole("button", {
        name: "Reload latest configuration",
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Target groups")).toHaveValue("beta");
    expect(
      screen.getByRole("button", { name: "Save configuration" }),
    ).toBeDisabled();
    const call = fetcher.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(call[1]!.body as string)).toEqual({
      enabled: true,
      target_groups: ["beta"],
      rollout_percentage: 25,
      version: 1,
    });
    await user.click(
      screen.getByRole("button", { name: "Reload latest configuration" }),
    );
    await waitFor(() =>
      expect(screen.getByLabelText("Target groups")).toHaveValue(""),
    );
  });
  it("validates percentage and duplicate groups locally", async () => {
    mockApi();
    render(<App />);
    const user = await login();
    await selectFlag(user);
    await user.clear(screen.getByLabelText("Rollout percentage"));
    await user.type(screen.getByLabelText("Rollout percentage"), "101");
    await user.click(
      screen.getByRole("button", { name: "Save configuration" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("whole number");
    await user.clear(screen.getByLabelText("Rollout percentage"));
    await user.type(screen.getByLabelText("Rollout percentage"), "0");
    await user.type(screen.getByLabelText("Target groups"), "beta{Enter}beta");
    await user.click(
      screen.getByRole("button", { name: "Save configuration" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("unique groups");
  });
  it("shows real successful false decisions, clears them on context change, and shows failure as error", async () => {
    let fail = false;
    const fetcher = mockApi((url) =>
      url.endsWith("/admin/evaluate") && fail
        ? json(errorBody("SERVICE_UNAVAILABLE", "Database unavailable"), 503)
        : undefined,
    );
    render(<App />);
    const user = await login();
    await selectFlag(user);
    await user.type(screen.getByLabelText("Synthetic user ID"), "user-003");
    await user.click(screen.getByRole("button", { name: "Evaluate user" }));
    expect(await screen.findByText("Disabled · false")).toBeInTheDocument();
    expect(screen.getByText("FLAG_DISABLED")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Synthetic user ID"), "x");
    expect(screen.queryByText("FLAG_DISABLED")).not.toBeInTheDocument();
    fail = true;
    await user.click(screen.getByRole("button", { name: "Evaluate user" }));
    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Disabled · false")).not.toBeInTheDocument();
    const call = fetcher.mock.calls.find(([url]) =>
      url.endsWith("/admin/evaluate"),
    )!;
    expect(JSON.parse(call[1]!.body as string).user.id).toBe("user-003");
  });
  it("confirms archival and displays real audit snapshots", async () => {
    const fetcher = mockApi((url, init) =>
      init?.method === "DELETE"
        ? new Response(null, { status: 204 })
        : url.includes("/audit")
          ? json({
              ...empty,
              total: 1,
              items: [
                {
                  id: "audit-1",
                  flag_key: flag.key,
                  environment: null,
                  action: "FLAG_CREATED",
                  actor: "seed",
                  before: null,
                  after: { key: flag.key },
                  created_at: flag.created_at,
                },
              ],
            })
          : undefined,
    );
    render(<App />);
    const user = await login();
    await selectFlag(user);
    expect(await screen.findByText("FLAG CREATED")).toBeInTheDocument();
    await user.click(screen.getByText("Before / after"));
    expect(screen.getByText(/"before": null/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Archive flag…" }));
    expect(
      fetcher.mock.calls.some(([, init]) => init?.method === "DELETE"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "Confirm archive" }));
    await screen.findByText("A little control goes a long way.");
  });
});
