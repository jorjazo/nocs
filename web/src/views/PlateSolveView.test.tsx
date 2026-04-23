import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { PlateSolveView } from "./PlateSolveView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("PlateSolveView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("shows installation status and triggers solve on a chosen image", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/platesolving/install",
        respond: (url, init) => {
          if (init.method === "POST") return { status: 202 };
          return {
            body: {
              installed: true,
              binary_path: "/x/astap_cli",
              db_dir: "/x/db",
              db_name: "H18",
              db_present: true,
              supported_platform: true,
              allow_network: false,
            },
          };
        },
      },
      {
        match: "/api/platesolving/install/progress",
        respond: {
          body: {
            phase: "idle",
            message: "",
            bytes_done: 0,
            bytes_total: 0,
            updated_at: "2026-01-01T00:00:00Z",
          },
        },
      },
      {
        match: /\/api\/images/,
        respond: {
          body: [
            {
              id: 7,
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
              dateObs: "2026",
              createdAt: "2026",
            },
          ],
        },
      },
      {
        match: "/api/platesolving/solve",
        respond: {
          body: {
            solved: true,
            image_id: 7,
            duration_ms: 100,
            solution: {
              ra_j2000_deg: 10,
              dec_j2000_deg: 41,
              pixel_scale_arcsec_per_pixel: 1,
              rotation_deg: 0,
              field_width_deg: 1,
              field_height_deg: 1,
              solver: "astap",
              solved_at: "2026-01-01T00:00:00Z",
              duration_ms: 100,
            },
          },
        },
      },
    ]);
    renderWithProviders(<PlateSolveView />);
    expect(await screen.findByText(/H18/)).toBeInTheDocument();
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "7");
    await user.click(screen.getByRole("button", { name: /Solve/ }));
    expect(await screen.findByText(/ra_j2000_deg/)).toBeInTheDocument();
    expect(calls.some((c) => c.url.endsWith("/api/platesolving/solve"))).toBe(true);
  });
});
