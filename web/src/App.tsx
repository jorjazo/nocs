import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "./auth/AuthProvider";
import { TokenGate } from "./auth/TokenGate";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: 1 },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TokenGate>
          <main style={{ padding: 16 }}>
            <h1>NOCS</h1>
            <p>web client bootstrap (Plan H)</p>
          </main>
        </TokenGate>
      </AuthProvider>
    </QueryClientProvider>
  );
}
