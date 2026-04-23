import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { FilterWheelView } from "./FilterWheelView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("FilterWheelView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("selects a slot on the only wheel", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            {
              id: "wh-1",
              indiName: "WheelSim",
              kind: "filterwheel",
              state: "IDLE",
              connected: true,
            },
          ],
        },
      },
      { match: /\/api\/filterwheels\/wh-1\/select/, respond: { status: 204 } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<FilterWheelView />);
    await screen.findByText("IDLE");
    await user.click(screen.getByRole("button", { name: /^Select$/ }));
    const c = calls.find((x) => x.url.endsWith("/api/filterwheels/wh-1/select"))!;
    expect(JSON.parse(String(c.init.body))).toEqual({ slot: 1 });
  });
});
