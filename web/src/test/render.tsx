import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "@/auth/AuthProvider";

export function renderWithProviders(
  ui: ReactElement,
  options: RenderOptions & { route?: string } = {},
) {
  const { route, ...rest } = options;
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <MemoryRouter initialEntries={[route ?? "/"]}>{ui}</MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
    rest,
  );
}
