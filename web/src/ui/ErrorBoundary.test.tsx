import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ErrorBoundary } from "./ErrorBoundary";

function Boom() {
  throw new Error("kaboom");
}

describe("ErrorBoundary", () => {
  it("renders the error UI when a child throws", () => {
    const orig = console.error;
    console.error = () => {};
    try {
      render(
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>,
      );
      expect(screen.getByText(/Something broke/i)).toBeInTheDocument();
      expect(screen.getByText(/kaboom/)).toBeInTheDocument();
    } finally {
      console.error = orig;
    }
  });
});
