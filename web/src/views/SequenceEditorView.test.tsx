import { afterEach, beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/render";
import { SequenceEditorView } from "./SequenceEditorView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SequenceEditorView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("submits a sequence and navigates to the runner", async () => {
    const { calls } = installFetchMock([
      {
        match: "/api/devices",
        respond: {
          body: [
            { id: "mount-1", indiName: "M", kind: "mount", state: "IDLE", connected: true },
            { id: "cam-1", indiName: "C", kind: "camera", state: "READY", connected: true },
          ],
        },
      },
      { match: /\/api\/sequences\?/, respond: { body: [] } },
      {
        match: "/api/sequences",
        respond: (url, init) => {
          if (init.method === "POST") {
            return {
              body: {
                id: 9,
                session_id: null,
                name: "Quick run",
                status: "PENDING",
                failure_reason: null,
                created_at: "2026",
                started_at: null,
                finished_at: null,
                current_step_index: null,
                current_sub_index: null,
                subs_completed: 0,
                subs_total: 5,
                definition: null,
              },
            };
          }
          return { body: [] };
        },
      },
    ]);
    const user = userEvent.setup();
    renderWithProviders(<SequenceEditorView />);
    await screen.findByRole("button", { name: /Submit & start/i });
    await user.click(screen.getByRole("button", { name: /Submit & start/i }));
    expect(calls.some((c) => c.url === "/api/sequences" && c.init.method === "POST")).toBe(true);
  });
});
