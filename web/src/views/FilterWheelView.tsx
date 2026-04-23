import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { useTopic } from "@/events/useTopic";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";

export function FilterWheelView() {
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  useTopic("filterwheel");
  const wheels = (devices.data ?? []).filter((d) => d.kind === "filterwheel");
  const [id, setId] = useState("");
  useEffect(() => {
    if (!id && wheels.length === 1) setId(wheels[0].id);
  }, [wheels, id]);
  const [slot, setSlot] = useState("1");
  const select = useMutation({
    mutationFn: () => devicesApi.selectSlot(id, { slot: Number(slot) }),
  });
  const wheel = wheels.find((w) => w.id === id);

  return (
    <div>
      <h1>Filter wheel</h1>
      <Card title="Select filter wheel">
        <select value={id} onChange={(e) => setId(e.target.value)}>
          <option value="">—</option>
          {wheels.map((w) => (
            <option key={w.id} value={w.id}>
              {w.id}
            </option>
          ))}
        </select>
        {wheel && (
          <span style={{ marginLeft: 12 }}>
            <DeviceStatePill state={wheel.state} />
          </span>
        )}
      </Card>
      <Card title="Move to slot">
        <label>
          Slot:&nbsp;
          <input type="number" min={1} value={slot} onChange={(e) => setSlot(e.target.value)} />
        </label>{" "}
        <button type="button" disabled={!id || select.isPending} onClick={() => select.mutate()}>
          Select
        </button>
        {select.error && (
          <p style={{ color: "var(--color-danger)" }}>{(select.error as Error).message}</p>
        )}
      </Card>
    </div>
  );
}
