const STATE_COLOR: Record<string, string> = {
  IDLE: "var(--color-text-muted)",
  TRACKING: "var(--color-success)",
  COOLING: "var(--color-accent)",
  READY: "var(--color-success)",
  EXPOSING: "var(--color-accent)",
  DOWNLOADING: "var(--color-accent)",
  SLEWING: "var(--color-accent)",
  PARKING: "var(--color-warning)",
  PARKED: "var(--color-text-muted)",
  MOVING: "var(--color-accent)",
  ERROR: "var(--color-danger)",
  E_STOPPED: "var(--color-danger)",
  DISCONNECTED: "var(--color-text-muted)",
};

export function DeviceStatePill({ state }: { state: string }) {
  const color = STATE_COLOR[state] ?? "var(--color-text-muted)";
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        padding: "2px 8px",
        borderRadius: 999,
        background: "var(--color-surface-2)",
        color,
        border: `1px solid ${color}`,
      }}
    >
      {state}
    </span>
  );
}
