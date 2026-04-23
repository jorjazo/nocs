import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { renderWithProviders } from "@/test/render";
import { DashboardView } from "./DashboardView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { setToken, clearToken } from "@/api/token";

describe("DashboardView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("renders the device list and a connect button", async () => {
    installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "mount-1",
              indiName: "Telescope Sim",
              kind: "mount",
              state: "IDLE",
              connected: false,
            },
            { id: "cam-1", indiName: "CCD Sim", kind: "camera", state: "READY", connected: true },
          ],
        },
      },
    ]);
    const { findByText, findAllByRole } = renderWithProviders(<DashboardView />);
    expect(await findByText("mount-1")).toBeInTheDocument();
    expect(await findByText("READY")).toBeInTheDocument();
    const buttons = await findAllByRole("button", { name: /Connect|Disconnect/ });
    expect(buttons.length).toBeGreaterThanOrEqual(2);
  });

  it("shows the empty-state hint when no devices are returned", async () => {
    installFetchMock([{ match: "/api/devices", respond: { body: [] } }]);
    const { findByText } = renderWithProviders(<DashboardView />);
    expect(await findByText(/No devices reported/i)).toBeInTheDocument();
  });
});
