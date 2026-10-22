import { describe, it, expect, vi } from "vitest";
import { createClient } from "./client";
import { evaluation } from "../test/fixtures";
describe("API boundary", () => {
  it("uses relative admin route and bearer header", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify(evaluation)));
    vi.stubGlobal("fetch", fetcher);
    await createClient("synthetic-token").evaluate(
      "new-checkout",
      "development",
      "user-003",
      [],
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/admin/evaluate",
      expect.objectContaining({
        headers: {
          Authorization: "Bearer synthetic-token",
          "Content-Type": "application/json",
        },
      }),
    );
  });
  it.each([
    {},
    { ...evaluation, value: "false" },
    { ...evaluation, bucket: 10 },
    { ...evaluation, reason: "UNRECOGNIZED" },
  ])("rejects malformed evaluation %j", async (payload) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(JSON.stringify(payload))),
    );
    await expect(
      createClient("synthetic").evaluate(
        "new-checkout",
        "development",
        "u",
        [],
      ),
    ).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
  it("rejects non-JSON success without exposing raw response", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response("<html>private diagnostic</html>")),
    );
    await expect(createClient("synthetic").list()).rejects.toMatchObject({
      code: "INVALID_RESPONSE",
    });
  });
});
