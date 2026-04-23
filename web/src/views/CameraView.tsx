import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { useTopic } from "@/events/useTopic";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";

export function CameraView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("camera");
  const cams = (devices.data ?? []).filter((d) => d.kind === "camera");
  const [id, setId] = useState("");
  useEffect(() => {
    if (!id && cams.length === 1) setId(cams[0].id);
  }, [cams, id]);

  const [duration, setDuration] = useState("5");
  const [filter, setFilter] = useState("");
  const [target, setTarget] = useState("");
  const [setpoint, setSetpoint] = useState("-10");

  const expose = useMutation({
    mutationFn: () =>
      devicesApi.expose(id, {
        durationSeconds: Number(duration),
        filter: filter || undefined,
        target: target || undefined,
      }),
  });
  const cool = useMutation({
    mutationFn: () => devicesApi.cool(id, { setpointCelsius: Number(setpoint) }),
  });

  const cam = cams.find((c) => c.id === id);

  return (
    <div>
      <h1>Camera</h1>
      <Card title="Select camera">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {cams.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id}
            </option>
          ))}
        </select>
        {cam && (
          <span style={{ marginLeft: 12 }}>
            <DeviceStatePill state={cam.state} />
          </span>
        )}
      </Card>

      <Card title="Expose">
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}>
            <span>Duration (s)</span>
            <input
              type="number"
              step="0.1"
              value={duration}
              onChange={(e) => setDuration(e.target.value)}
            />
          </label>
          <label style={{ display: "contents" }}>
            <span>Filter (optional)</span>
            <input value={filter} onChange={(e) => setFilter(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Target (optional)</span>
            <input value={target} onChange={(e) => setTarget(e.target.value)} />
          </label>
        </div>
        <p>
          <button type="button" disabled={!id || expose.isPending} onClick={() => expose.mutate()}>
            Expose
          </button>
        </p>
        {expose.error && (
          <p style={{ color: "var(--color-danger)" }}>{(expose.error as Error).message}</p>
        )}
      </Card>

      <Card title="Cooling">
        <label>
          Setpoint (°C):&nbsp;
          <input
            type="number"
            step="0.1"
            value={setpoint}
            onChange={(e) => setSetpoint(e.target.value)}
          />
        </label>{" "}
        <button type="button" disabled={!id || cool.isPending} onClick={() => cool.mutate()}>
          Set cooling
        </button>
        {cool.error && (
          <p style={{ color: "var(--color-danger)" }}>{(cool.error as Error).message}</p>
        )}
      </Card>
    </div>
  );
}
