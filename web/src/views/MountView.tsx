import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";
import { useTopic } from "@/events/useTopic";

export function MountView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("mount");
  useTopic("device_connection");

  const mounts = (devices.data ?? []).filter((d) => d.kind === "mount");
  const [mountId, setMountId] = useState<string>("");
  useEffect(() => {
    if (!mountId && mounts.length === 1) setMountId(mounts[0].id);
  }, [mounts, mountId]);

  const [ra, setRa] = useState("0.000");
  const [dec, setDec] = useState("0.0");

  const slew = useMutation({
    mutationFn: () => devicesApi.slew(mountId, { raHours: Number(ra), decDegrees: Number(dec) }),
  });
  const sync = useMutation({
    mutationFn: () => devicesApi.sync(mountId, { raHours: Number(ra), decDegrees: Number(dec) }),
  });
  const park = useMutation({ mutationFn: () => devicesApi.park(mountId) });

  return (
    <div>
      <h1>Mount</h1>
      <Card title="Select mount">
        <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
          <option value="">—</option>
          {mounts.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id}
            </option>
          ))}
        </select>
        {mountId && mounts.find((m) => m.id === mountId) && (
          <span style={{ marginLeft: 12 }}>
            <DeviceStatePill state={mounts.find((m) => m.id === mountId)!.state} />
          </span>
        )}
      </Card>

      <Card title="Manual control">
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}>
            <span>RA (hours, 0–24)</span>
            <input type="number" step="0.001" value={ra} onChange={(e) => setRa(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Dec (degrees, −90–90)</span>
            <input type="number" step="0.01" value={dec} onChange={(e) => setDec(e.target.value)} />
          </label>
        </div>
        <p>
          <button type="button" disabled={!mountId || slew.isPending} onClick={() => slew.mutate()}>
            Slew
          </button>{" "}
          <button type="button" disabled={!mountId || sync.isPending} onClick={() => sync.mutate()}>
            Sync
          </button>{" "}
          <button type="button" disabled={!mountId || park.isPending} onClick={() => park.mutate()}>
            Park
          </button>
        </p>
        {slew.error && (
          <p style={{ color: "var(--color-danger)" }}>{(slew.error as Error).message}</p>
        )}
        {sync.error && (
          <p style={{ color: "var(--color-danger)" }}>{(sync.error as Error).message}</p>
        )}
        {park.error && (
          <p style={{ color: "var(--color-danger)" }}>{(park.error as Error).message}</p>
        )}
      </Card>
    </div>
  );
}
