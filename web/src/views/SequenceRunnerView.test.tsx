import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { renderWithProviders } from "@/test/render";
import { SequenceRunnerView } from "./SequenceRunnerView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SequenceRunnerView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("renders status and progress for an existing sequence", async () => {
    installFetchMock([
      {
        match: "/api/sequences/42",
        respond: {
          body: {
            id: 42,
            session_id: null,
            name: "Demo",
            status: "RUNNING",
            failure_reason: null,
            created_at: "2026",
            started_at: "2026",
            finished_at: null,
            current_step_index: 0,
            current_sub_index: 1,
            subs_completed: 1,
            subs_total: 5,
            definition: null,
          },
        },
      },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/sequences/:id" element={<SequenceRunnerView />} />
      </Routes>,
      { route: "/sequences/42" },
    );
    expect(await screen.findByText(/Demo/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "20");
  });
});
