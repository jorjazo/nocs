import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";
import { clearToken, setToken } from "./api/token";

describe("App shell", () => {
  beforeEach(() => {
    clearToken();
  });
  afterEach(() => clearToken());

  it("renders the login panel without a token", () => {
    render(<App />);
    expect(screen.getByLabelText(/Bearer token/i)).toBeInTheDocument();
  });

  it("renders the navigation once a token is set", () => {
    setToken("dev");
    render(<App />);
    expect(screen.getByRole("link", { name: /Dashboard/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Sequences/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Safety/i })).toBeInTheDocument();
  });
});
