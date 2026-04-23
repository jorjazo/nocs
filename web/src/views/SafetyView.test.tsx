import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SafetyView } from "./SafetyView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SafetyView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("requires confirmation before e-stop and surfaces latched rules", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/safety/rules",
        respond: {
          body: {
            rules: [
              { name: "rain", action: "e_stop", when: { rain_detected: true }, latched: true },
            ],
            latched: ["rain"],
            activeTargetId: null,
          },
        },
      },
      { match: "/api/safety/e-stop", respond: { body: { status: "ok" } } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<SafetyView />);
    expect(await screen.findByText(/Latched:/)).toBeInTheDocument();
    const btn = screen.getByRole("button", { name: /^E-STOP$/ });
    await user.click(btn);
    await user.click(await screen.findByRole("button", { name: /Confirm E-STOP/ }));
    expect(calls.some((c) => c.url.endsWith("/api/safety/e-stop"))).toBe(true);
  });
});
