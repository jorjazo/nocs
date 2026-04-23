import { describe, it, expect, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { screen } from "@testing-library/react";
import { TokenGate } from "./TokenGate";
import { clearToken, getToken } from "@/api/token";
import { renderWithProviders } from "@/test/render";

describe("TokenGate", () => {
  beforeEach(() => clearToken());

  it("shows the login panel when no token is set", () => {
    renderWithProviders(
      <TokenGate>
        <div>secret</div>
      </TokenGate>,
    );
    expect(screen.getByRole("heading", { name: /NOCS/i })).toBeInTheDocument();
    expect(screen.queryByText("secret")).toBeNull();
  });

  it("reveals children once a token is entered", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TokenGate>
        <div>secret</div>
      </TokenGate>,
    );
    const input = screen.getByLabelText(/Bearer token/i);
    await user.type(input, "hunter2");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("secret")).toBeInTheDocument();
    expect(getToken()).toBe("hunter2");
  });
});
