import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { useTopic } from "@/events/useTopic";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";

export function FocuserView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("focuser");
  const focs = (devices.data ?? []).filter((d) => d.kind === "focuser");
  const [id, setId] = useState("");
  useEffect(() => {
    if (!id && focs.length === 1) setId(focs[0].id);
  }, [focs, id]);

  const [absolute, setAbsolute] = useState("0");
  const [offset, setOffset] = useState("0");

  const moveAbs = useMutation({
    mutationFn: () => devicesApi.move(id, { position: Number(absolute) }),
  });
  const moveRel = useMutation({
    mutationFn: () => devicesApi.move(id, { offset: Number(offset) }),
  });

  const f = focs.find((x) => x.id === id);

  return (
    <div>
      <h1>Focuser</h1>
      <Card title="Select focuser">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {focs.map((x) => (
            <option key={x.id} value={x.id}>
              {x.id}
            </option>
          ))}
        </select>
        {f && (
          <span style={{ marginLeft: 12 }}>
            <DeviceStatePill state={f.state} />
          </span>
        )}
      </Card>

      <Card title="Move (absolute)">
        <input type="number" value={absolute} onChange={(e) => setAbsolute(e.target.value)} />{" "}
        <button type="button" disabled={!id || moveAbs.isPending} onClick={() => moveAbs.mutate()}>
          Move to
        </button>
        {moveAbs.error && (
          <p style={{ color: "var(--color-danger)" }}>{(moveAbs.error as Error).message}</p>
        )}
      </Card>

      <Card title="Move (relative)">
        <input type="number" value={offset} onChange={(e) => setOffset(e.target.value)} />{" "}
        <button type="button" disabled={!id || moveRel.isPending} onClick={() => moveRel.mutate()}>
          Move by
        </button>
        {moveRel.error && (
          <p style={{ color: "var(--color-danger)" }}>{(moveRel.error as Error).message}</p>
        )}
      </Card>

      <Card title="Autofocus">
        <p>
          v0.1 ships the no-op autofocus strategy. The Sequence engine runs it as a pre-step; a
          manual trigger here is reserved for v0.2 (sweep).
        </p>
        <button type="button" disabled>
          Run autofocus (v0.2)
        </button>
      </Card>
    </div>
  );
}
