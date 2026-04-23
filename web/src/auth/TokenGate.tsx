import { useContext, type ReactNode } from "react";
import { AuthContext } from "./AuthContext";
import { LoginPanel } from "./LoginPanel";

export function TokenGate({ children }: { children: ReactNode }) {
  const { token } = useContext(AuthContext);
  if (!token) return <LoginPanel />;
  return <>{children}</>;
}
