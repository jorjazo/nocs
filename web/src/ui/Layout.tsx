import { Outlet } from "react-router-dom";
import { NavBar } from "./NavBar";
import { ErrorBoundary } from "./ErrorBoundary";

export function Layout() {
  return (
    <>
      <NavBar />
      <main style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}
