import { useEventStream } from "@/events/EventStream";

const COLOR: Record<string, string> = {
  idle: "var(--color-text-muted)",
  connecting: "var(--color-warning)",
  open: "var(--color-success)",
  closed: "var(--color-text-muted)",
  error: "var(--color-danger)",
};

export function ConnectionPill() {
  const { state } = useEventStream();
  return (
    <span
      role="status"
      aria-label={`event stream ${state}`}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "2px 10px",
        borderRadius: 999,
        background: "var(--color-surface-2)",
        color: COLOR[state],
        fontFamily: "var(--font-mono)",
        fontSize: 12,
      }}
    >
      <span style={{ width: 8, height: 8, background: COLOR[state], borderRadius: 999 }} />
      {state}
    </span>
  );
}
