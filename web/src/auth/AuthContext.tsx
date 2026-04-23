import { createContext } from "react";

export interface AuthState {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

export const AuthContext = createContext<AuthState>({
  token: null,
  setToken: () => {},
  clearToken: () => {},
});
