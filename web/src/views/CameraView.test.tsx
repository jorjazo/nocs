import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { CameraView } from "./CameraView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("CameraView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("exposes the only camera with chosen duration", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "cam-1",
              indiName: "CCD Sim",
              kind: "camera",
              state: "READY",
              connected: true,
            },
          ],
        },
      },
      { match: /\/api\/cameras\/cam-1\/expose/, respond: { status: 204 } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<CameraView />);
    await screen.findByText("READY");
    await user.click(screen.getByRole("button", { name: /^Expose$/ }));
    const ex = calls.find((c) => c.url.endsWith("/api/cameras/cam-1/expose"))!;
    expect(JSON.parse(String(ex.init.body))).toMatchObject({ durationSeconds: 5 });
  });
});
