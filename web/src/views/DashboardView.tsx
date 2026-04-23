import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { devicesApi } from "@/api/endpoints/devices";
import { useEventStream } from "@/events/EventStream";
import type { DeviceView } from "@/api/types";
import { Card } from "@/ui/Card";
import { DeviceStatePill } from "@/ui/DeviceStatePill";

export function DashboardView() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const {
    data: devices,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["devices"],
    queryFn: devicesApi.list,
  });

  useEffect(() => {
    const topics = ["device_connection", "mount", "camera", "filterwheel", "focuser"];
    const unsubs = topics.map((t) =>
      subscribe(t, () => {
        void qc.invalidateQueries({ queryKey: ["devices"] });
      }),
    );
    return () => unsubs.forEach((u) => u());
  }, [subscribe, qc]);

  const connect = useMutation({
    mutationFn: (id: string) => devicesApi.connect(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const disconnect = useMutation({
    mutationFn: (id: string) => devicesApi.disconnect(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });

  return (
    <div>
      <h1>Hardware</h1>
      <Card title="Devices">
        {isLoading && <p>Loading…</p>}
        {error && <p style={{ color: "var(--color-danger)" }}>{(error as Error).message}</p>}
        {devices && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Kind</th>
                <th>INDI name</th>
                <th>State</th>
                <th>Connected</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {devices.map((d: DeviceView) => (
                <tr key={d.id}>
                  <td>
                    <code>{d.id}</code>
                  </td>
                  <td>{d.kind}</td>
                  <td>{d.indiName}</td>
                  <td>
                    <DeviceStatePill state={d.state} />
                  </td>
                  <td>{d.connected ? "yes" : "no"}</td>
                  <td>
                    {d.connected ? (
                      <button type="button" onClick={() => disconnect.mutate(d.id)}>
                        Disconnect
                      </button>
                    ) : (
                      <button type="button" onClick={() => connect.mutate(d.id)}>
                        Connect
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {devices.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ color: "var(--color-text-muted)" }}>
                    No devices reported. Check <code>nocs.indi.mode</code> in{" "}
                    <code>config.yaml</code>.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
