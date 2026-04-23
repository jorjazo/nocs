export function ProgressBar({ value, total }: { value: number; total: number }) {
  const pct = total <= 0 ? 0 : Math.min(100, Math.max(0, Math.round((value / total) * 100)));
  return (
    <div
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
      style={{
        background: "var(--color-surface-2)",
        height: 10,
        borderRadius: 999,
        border: "1px solid var(--color-border)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: `${pct}%`,
          height: "100%",
          background: "var(--color-accent)",
          transition: "width 0.2s ease",
        }}
      />
    </div>
  );
}
