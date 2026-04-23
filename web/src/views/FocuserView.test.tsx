import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { FocuserView } from "./FocuserView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("FocuserView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("submits a relative move", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "f-1",
              indiName: "FocSim",
              kind: "focuser",
              state: "IDLE",
              connected: true,
            },
          ],
        },
      },
      { match: /\/api\/focusers\/f-1\/move/, respond: { status: 204 } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<FocuserView />);
    await screen.findByText("IDLE");
    const offsetInput = screen.getAllByRole("spinbutton")[1];
    await user.clear(offsetInput);
    await user.type(offsetInput, "50");
    await user.click(screen.getByRole("button", { name: /Move by/ }));
    const c = calls.find((x) => x.url.endsWith("/api/focusers/f-1/move"))!;
    expect(JSON.parse(String(c.init.body))).toEqual({ offset: 50 });
  });
});
