import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { renderWithProviders } from "@/test/render";
import { SessionsView } from "./SessionsView";
import { installFetchMock, uninstallFetchMock } from "@/test/mocks";
import { clearToken, setToken } from "@/api/token";

describe("SessionsView", () => {
  beforeEach(() => {
    clearToken();
    setToken("dev");
  });
  afterEach(() => {
    uninstallFetchMock();
    clearToken();
  });

  it("lists sessions and shows event detail when an id is in the route", async () => {
    installFetchMock([
      {
        match: /\/api\/sessions$/,
        respond: {
          body: [{ id: 1, name: "first", opened_at: "2026-04-23T00:00:00Z", closed_at: null }],
        },
      },
      {
        match: /\/api\/sessions\/1$/,
        respond: {
          body: {
            session: { id: 1, name: "first", opened_at: "2026", closed_at: null },
            events: [{ id: 100, ts: "2026", topic: "system", type: "boot", payload_json: "{}" }],
          },
        },
      },
    ]);
    renderWithProviders(
      <Routes>
        <Route path="/sessions/:id" element={<SessionsView />} />
        <Route path="/sessions" element={<SessionsView />} />
      </Routes>,
      { route: "/sessions/1" },
    );
    expect(await screen.findByText("first")).toBeInTheDocument();
    expect(await screen.findByText("boot")).toBeInTheDocument();
  });
});
