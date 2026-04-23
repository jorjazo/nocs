import type { ReactNode } from "react";

export function Card({
  title,
  actions,
  children,
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius)",
        padding: "var(--space-4)",
        marginBottom: "var(--space-4)",
      }}
    >
      {(title || actions) && (
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "var(--space-3)",
          }}
        >
          <h2 style={{ margin: 0, fontSize: 16 }}>{title}</h2>
          <div>{actions}</div>
        </header>
      )}
      {children}
    </section>
  );
}
