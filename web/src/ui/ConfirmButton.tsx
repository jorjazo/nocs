import { useState } from "react";

export function ConfirmButton({
  label,
  confirmLabel = "Confirm",
  onConfirm,
  danger,
}: {
  label: string;
  confirmLabel?: string;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const [armed, setArmed] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        if (!armed) {
          setArmed(true);
          setTimeout(() => setArmed(false), 4000);
          return;
        }
        setArmed(false);
        onConfirm();
      }}
      style={
        danger && armed
          ? { borderColor: "var(--color-danger)", color: "var(--color-danger)" }
          : undefined
      }
    >
      {armed ? confirmLabel : label}
    </button>
  );
}
