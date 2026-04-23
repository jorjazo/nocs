import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { apiFetch, ApiError } from "./client";
import { setToken, clearToken } from "./token";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";

function headersToRecord(h: RequestInit["headers"]): Record<string, string> {
  if (!h) return {};
  if (h instanceof Headers) {
    return Object.fromEntries(h.entries());
  }
  if (Array.isArray(h)) {
    return Object.fromEntries(h);
  }
  return h as Record<string, string>;
}

describe("apiFetch", () => {
  beforeEach(() => clearToken());
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("attaches the bearer token", async () => {
    setToken("hunter2");
    const { calls } = installFetchMock([
      { match: "/api/config", respond: { body: { foo: "bar" } } },
    ]);
    const out = await apiFetch<Record<string, string>>("/api/config");
    expect(out).toEqual({ foo: "bar" });
    expect(headersToRecord(calls[0].init.headers)).toMatchObject({
      Authorization: "Bearer hunter2",
    });
  });

  it("throws ApiError on 4xx with parsed body", async () => {
    installFetchMock([
      { match: "/api/safety/e-stop", respond: { status: 400, body: { error: "nope" } } },
    ]);
    await expect(
      apiFetch("/api/safety/e-stop", { method: "POST", body: {} }),
    ).rejects.toMatchObject({ status: 400, message: "nope" } satisfies Partial<ApiError>);
  });

  it("returns undefined on 204", async () => {
    installFetchMock([{ match: /\/api\/devices\/.*\/connect/, respond: { status: 204 } }]);
    const out = await apiFetch<void>("/api/devices/mount-1/connect", { method: "POST" });
    expect(out).toBeUndefined();
  });
});
