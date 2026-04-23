import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { AuthContext } from "./AuthContext";
import { clearToken as drop, getToken, setToken as save } from "@/api/token";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(() => getToken());

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === "nocs.token") setTokenState(e.newValue);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setToken = useCallback((t: string) => {
    save(t);
    setTokenState(t);
  }, []);
  const clearToken = useCallback(() => {
    drop();
    setTokenState(null);
  }, []);

  const value = useMemo(() => ({ token, setToken, clearToken }), [token, setToken, clearToken]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
