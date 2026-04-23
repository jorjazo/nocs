import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { TargetsView } from "./TargetsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("TargetsView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("searches and shows details with a slew button bound to a mount", async () => {
    const user = userEvent.setup();
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "mount-1",
              indiName: "TelescopeSim",
              kind: "mount",
              state: "IDLE",
              connected: true,
            },
          ],
        },
      },
      {
        match: /\/api\/targets\/search\?q=M31/,
        respond: {
          body: [
            {
              target: {
                id: "messier:M31",
                primaryName: "Andromeda Galaxy",
                aliases: ["M31"],
                kind: "GALAXY",
                raJ2000Deg: 10.6847,
                decJ2000Deg: 41.2687,
                constellation: "And",
                magnitude: 3.4,
                sizeArcmin: 190.0,
                notes: "",
              },
              observation: {
                altitudeDeg: 45,
                azimuthDeg: 90,
                airmass: 1.4,
                hourAngleHours: 2.3,
                transitInHours: 1.1,
              },
            },
          ],
        },
      },
      { match: /\/api\/mounts\/mount-1\/slew$/, respond: { status: 204 } },
    ]);
    renderWithProviders(<TargetsView />);
    await user.type(screen.getByPlaceholderText(/M31/), "M31");
    await user.click(screen.getByRole("button", { name: /search/i }));
    await user.click(await screen.findByText("Andromeda Galaxy"));
    const mountSelect = screen.getByLabelText(/mount/i, { selector: "select" });
    await user.selectOptions(mountSelect, "mount-1");
    await user.click(screen.getByRole("button", { name: /^Slew$/ }));
    expect(calls.some((c) => c.url.includes("/api/mounts/mount-1/slew"))).toBe(true);
  });
});
