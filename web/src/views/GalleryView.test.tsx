import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { GalleryView } from "./GalleryView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("GalleryView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("renders thumbnails and triggers a delete", async () => {
    const { calls } = installFetchMock([
      {
        match: /\/api\/images(\?.*)?$/,
        respond: {
          body: [
            {
              id: 1,
              sessionId: null,
              device: "cam-1",
              filter: "L",
              target: "M31",
              exposureSec: 5,
              step: "L",
              seq: 0,
              fitsPath: "/p",
              thumbPath: "/t",
              bytes: 100,
              width: 1,
              height: 1,
              bitpix: 16,
              dateObs: null,
              createdAt: "2026",
            },
          ],
        },
      },
      { match: /\/api\/images\/1$/, respond: { status: 204 } },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<GalleryView />);
    expect(await screen.findByAltText("#1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Delete/ }));
    expect(calls.some((c) => c.url.endsWith("/api/images/1") && c.init.method === "DELETE")).toBe(
      true,
    );
  });
});
