import { useContext, useState } from "react";
import { AuthContext } from "./AuthContext";

export function LoginPanel() {
  const { setToken } = useContext(AuthContext);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <main style={{ maxWidth: 360, margin: "8vh auto", padding: 24 }}>
      <h1>NOCS</h1>
      <p>
        Enter the bearer token from <code>config.yaml</code>.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) {
            setError("Token is required");
            return;
          }
          setError(null);
          setToken(value.trim());
        }}
      >
        <label style={{ display: "block", marginBottom: 8 }}>
          <span>Bearer token</span>
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            style={{ width: "100%", marginTop: 4 }}
            autoFocus
          />
        </label>
        {error && <p style={{ color: "var(--color-danger)" }}>{error}</p>}
        <button type="submit">Sign in</button>
      </form>
    </main>
  );
}
