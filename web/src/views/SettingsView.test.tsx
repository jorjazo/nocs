import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SettingsView } from "./SettingsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SettingsView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("loads config and observatories, allows activating one", async () => {
    const user = userEvent.setup();
    const { calls } = installFetchMock([
      {
        match: "/api/config",
        respond: (url, init) =>
          (init.method ?? "GET") === "PATCH" ? { body: { foo: "bar2" } } : { body: { foo: "bar" } },
      },
      {
        match: "/api/observatories",
        respond: {
          body: [
            {
              id: 1,
              name: "Home",
              latitudeDeg: 51.5,
              longitudeDeg: -0.12,
              elevationM: 30,
              timezone: "UTC",
              horizonMaskJson: null,
              active: false,
            },
          ],
        },
      },
      { match: /\/api\/observatories\/1\/activate$/, respond: { body: { id: 1, active: true } } },
    ]);
    renderWithProviders(<SettingsView />);
    expect(await screen.findByDisplayValue("bar")).toBeInTheDocument();
    expect(await screen.findByText("Home")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Activate/i }));
    expect(calls.some((c) => c.url.endsWith("/api/observatories/1/activate"))).toBe(true);
  });
});
