import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { MountView } from "./MountView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("MountView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("auto-selects the only mount and parks it", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "mount-1",
              indiName: "TelescopeSim",
              kind: "mount",
              state: "TRACKING",
              connected: true,
            },
          ],
        },
      },
      { match: /\/api\/mounts\/mount-1\/park/, respond: { status: 204 } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<MountView />);
    expect(await screen.findByText("TRACKING")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Park$/ }));
    expect(calls.some((c) => c.url.endsWith("/api/mounts/mount-1/park"))).toBe(true);
  });
});
