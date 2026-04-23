import { useEffect } from "react";
import { Link, Outlet } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { safetyApi } from "@/api/endpoints/safety";
import { useEventStream } from "@/events/EventStream";
import { Banner } from "./Banner";
import { ErrorBoundary } from "./ErrorBoundary";
import { NavBar } from "./NavBar";

export function Layout() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const safety = useQuery({
    queryKey: ["safety"],
    queryFn: safetyApi.status,
    refetchInterval: 30_000,
  });
  useEffect(() => {
    return subscribe("safety", () => {
      void qc.invalidateQueries({ queryKey: ["safety"] });
    });
  }, [subscribe, qc]);

  return (
    <>
      <NavBar />
      <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
        {safety.data && safety.data.latched.length > 0 && (
          <Banner
            kind="danger"
            action={
              <Link to="/safety">
                <button type="button">Open Safety</button>
              </Link>
            }
          >
            <strong>Safety latched:</strong> {safety.data.latched.join(", ")}
          </Banner>
        )}
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
