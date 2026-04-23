import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";
import { clearToken, setToken } from "./api/token";

describe("App", () => {
  beforeEach(() => clearToken());
  afterEach(() => clearToken());

  it("shows the login panel before a token is set", () => {
    render(<App />);
    expect(screen.getByLabelText(/Bearer token/i)).toBeInTheDocument();
  });

  it("renders the bootstrap message after a token is set", () => {
    setToken("dev-token");
    render(<App />);
    expect(screen.getByText(/web client bootstrap/i)).toBeInTheDocument();
  });
});
