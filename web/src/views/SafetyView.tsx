import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { safetyApi } from "@/api/endpoints/safety";
import { useEventStream } from "@/events/EventStream";
import { Banner } from "@/ui/Banner";
import { Card } from "@/ui/Card";
import { ConfirmButton } from "@/ui/ConfirmButton";

export function SafetyView() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["safety"], queryFn: safetyApi.status });
  const { subscribe } = useEventStream();
  useEffect(() => {
    return subscribe("safety", () => {
      void qc.invalidateQueries({ queryKey: ["safety"] });
    });
  }, [subscribe, qc]);

  const reload = useMutation({
    mutationFn: () => safetyApi.reload(),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["safety"] }),
  });
  const eStop = useMutation({
    mutationFn: (reason: string) => safetyApi.eStop(reason),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["safety"] }),
  });
  const reset = useMutation({
    mutationFn: () => safetyApi.reset(),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["safety"] }),
  });

  const [reason, setReason] = useState("manual");
  const [sensor, setSensor] = useState("rain");
  const [values, setValues] = useState('{"rain": true}');
  const postReading = useMutation({
    mutationFn: () => {
      let parsed: Record<string, number | string | boolean>;
      try {
        parsed = JSON.parse(values) as Record<string, number | string | boolean>;
      } catch {
        throw new Error("values must be JSON object");
      }
      return safetyApi.postReading({ sensor, values: parsed });
    },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["safety"] }),
  });

  const [target, setTarget] = useState({ targetId: "", ra: "0", dec: "0" });
  const setActive = useMutation({
    mutationFn: () =>
      safetyApi.setActiveTarget({
        targetId: target.targetId,
        raJ2000Deg: Number(target.ra),
        decJ2000Deg: Number(target.dec),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["safety"] }),
  });

  return (
    <div>
      <h1>Safety</h1>
      {status.data && status.data.latched.length > 0 && (
        <Banner
          kind="danger"
          action={
            <button type="button" onClick={() => reset.mutate()}>
              Reset
            </button>
          }
        >
          <strong>Latched:</strong> {status.data.latched.join(", ")}
        </Banner>
      )}

      <Card
        title="Loaded rules"
        actions={
          <button type="button" onClick={() => reload.mutate()}>
            Reload safety.yaml
          </button>
        }
      >
        {status.isLoading && <p>Loading…</p>}
        {status.data && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>When</th>
                <th>Action</th>
                <th>Latched</th>
              </tr>
            </thead>
            <tbody>
              {status.data.rules.map((r) => (
                <tr key={r.name}>
                  <td>{r.name}</td>
                  <td>
                    <code>{JSON.stringify(r.when)}</code>
                  </td>
                  <td>
                    <code>{r.action}</code>
                  </td>
                  <td>{r.latched ? "yes" : ""}</td>
                </tr>
              ))}
              {status.data.rules.length === 0 && (
                <tr>
                  <td colSpan={4} style={{ color: "var(--color-text-muted)" }}>
                    No rules loaded.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Emergency stop">
        <p>Aborts the running exposure, stops the sequence, parks the mount, halts cooling.</p>
        <input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="reason"
        />{" "}
        <ConfirmButton
          label="E-STOP"
          confirmLabel="Confirm E-STOP"
          danger
          onConfirm={() => eStop.mutate(reason)}
        />
        {eStop.error && (
          <p style={{ color: "var(--color-danger)" }}>{(eStop.error as Error).message}</p>
        )}
      </Card>

      <Card title="Post test sensor reading">
        <label>
          Sensor <input value={sensor} onChange={(e) => setSensor(e.target.value)} />
        </label>{" "}
        <label>
          Values (JSON)
          <input
            style={{ width: 320 }}
            value={values}
            onChange={(e) => setValues(e.target.value)}
          />
        </label>{" "}
        <button type="button" onClick={() => postReading.mutate()}>
          Submit
        </button>
        {postReading.error && (
          <p style={{ color: "var(--color-danger)" }}>{(postReading.error as Error).message}</p>
        )}
      </Card>

      <Card title="Active target (drives altitude rules)">
        <label>
          Target ID{" "}
          <input
            value={target.targetId}
            onChange={(e) => setTarget({ ...target, targetId: e.target.value })}
          />
        </label>{" "}
        <label>
          RA (°){" "}
          <input
            type="number"
            value={target.ra}
            onChange={(e) => setTarget({ ...target, ra: e.target.value })}
          />
        </label>{" "}
        <label>
          Dec (°){" "}
          <input
            type="number"
            value={target.dec}
            onChange={(e) => setTarget({ ...target, dec: e.target.value })}
          />
        </label>{" "}
        <button type="button" disabled={!target.targetId} onClick={() => setActive.mutate()}>
          Set active
        </button>
        {status.data?.activeTargetId && (
          <p>
            Current active target: <code>{status.data.activeTargetId}</code>
          </p>
        )}
      </Card>
    </div>
  );
}
