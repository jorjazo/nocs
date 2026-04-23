import type { ReactNode } from "react";

export type BannerKind = "info" | "warning" | "danger" | "success";

const BG: Record<BannerKind, string> = {
  info: "var(--color-surface-2)",
  warning: "rgba(241, 193, 77, 0.15)",
  danger: "rgba(255, 107, 107, 0.18)",
  success: "rgba(92, 218, 166, 0.15)",
};
const BORDER: Record<BannerKind, string> = {
  info: "var(--color-border)",
  warning: "var(--color-warning)",
  danger: "var(--color-danger)",
  success: "var(--color-success)",
};

export function Banner({
  kind,
  children,
  action,
}: {
  kind: BannerKind;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div
      role="status"
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        justifyContent: "space-between",
        padding: "var(--space-3) var(--space-4)",
        background: BG[kind],
        borderLeft: `4px solid ${BORDER[kind]}`,
        borderRadius: "var(--radius)",
        marginBottom: "var(--space-3)",
      }}
    >
      <div>{children}</div>
      {action}
    </div>
  );
}
