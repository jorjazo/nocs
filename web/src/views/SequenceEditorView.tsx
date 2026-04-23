import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { devicesApi } from "@/api/endpoints/devices";
import { sequencesApi } from "@/api/endpoints/sequences";
import type { PreStepDto, SequenceDefinitionDto, SequenceStepDto } from "@/api/types";
import { Card } from "@/ui/Card";

const EMPTY_STEP: SequenceStepDto = { filter: "L", exposure_s: 30, count: 5 };

export function SequenceEditorView() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const recent = useQuery({
    queryKey: ["sequences", { limit: 20 }],
    queryFn: () => sequencesApi.list({ limit: 20 }),
  });

  const [name, setName] = useState("Quick run");
  const [targetId, setTargetId] = useState("");
  const [steps, setSteps] = useState<SequenceStepDto[]>([{ ...EMPTY_STEP }]);
  const [pre, setPre] = useState<PreStepDto[]>([]);
  const [dither, setDither] = useState({ enabled: false, pixels: 10, every_n_subs: 1 });
  const [mountId, setMountId] = useState("");
  const [cameraId, setCameraId] = useState("");
  const [filterWheelId, setFilterWheelId] = useState("");
  const [focuserId, setFocuserId] = useState("");

  const submit = useMutation({
    mutationFn: () => {
      const def: SequenceDefinitionDto = {
        name,
        target_id: targetId || undefined,
        dither,
        pre_steps: pre,
        steps,
        device_ids: {
          mount_id: mountId || undefined,
          camera_id: cameraId || undefined,
          filter_wheel_id: filterWheelId || undefined,
          focuser_id: focuserId || undefined,
        },
      };
      return sequencesApi.submit(def);
    },
    onSuccess: (run) => {
      void qc.invalidateQueries({ queryKey: ["sequences", { limit: 20 }] });
      navigate(`/sequences/${run.id}`);
    },
  });

  const addStep = () => setSteps((s) => [...s, { ...EMPTY_STEP }]);
  const removeStep = (i: number) => setSteps((s) => s.filter((_, j) => j !== i));
  const setStep = (i: number, patch: Partial<SequenceStepDto>) =>
    setSteps((s) => s.map((x, j) => (j === i ? { ...x, ...patch } : x)));

  const togglePre = (t: PreStepDto["type"]) =>
    setPre((arr) =>
      arr.find((p) => p.type === t) ? arr.filter((p) => p.type !== t) : [...arr, { type: t }],
    );

  const dev = (kind: string) => (devices.data ?? []).filter((d) => d.kind === kind);

  return (
    <div>
      <h1>Sequences</h1>

      <Card
        title="Editor"
        actions={
          <button
            type="button"
            disabled={submit.isPending || steps.length === 0}
            onClick={() => submit.mutate()}
          >
            Submit & start
          </button>
        }
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "auto 1fr",
            gap: 8,
            marginBottom: 12,
          }}
        >
          <label style={{ display: "contents" }}>
            <span>Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Target ID</span>
            <input
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              placeholder="messier:M31"
            />
          </label>
          <label style={{ display: "contents" }}>
            <span>Mount</span>
            <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
              <option value="">—</option>
              {dev("mount").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "contents" }}>
            <span>Camera</span>
            <select value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
              <option value="">—</option>
              {dev("camera").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "contents" }}>
            <span>Filter wheel</span>
            <select value={filterWheelId} onChange={(e) => setFilterWheelId(e.target.value)}>
              <option value="">—</option>
              {dev("filterwheel").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id}
                </option>
              ))}
            </select>
          </label>
          <label style={{ display: "contents" }}>
            <span>Focuser</span>
            <select value={focuserId} onChange={(e) => setFocuserId(e.target.value)}>
              <option value="">—</option>
              {dev("focuser").map((d) => (
                <option key={d.id} value={d.id}>
                  {d.id}
                </option>
              ))}
            </select>
          </label>
        </div>
        <h3>Pre-steps</h3>
        <label>
          <input
            type="checkbox"
            checked={!!pre.find((p) => p.type === "slew_and_sync")}
            onChange={() => togglePre("slew_and_sync")}
          />{" "}
          Slew + plate-solve + sync
        </label>
        <br />
        <label>
          <input
            type="checkbox"
            checked={!!pre.find((p) => p.type === "autofocus")}
            onChange={() => togglePre("autofocus")}
          />{" "}
          Autofocus
        </label>
        <h3>Steps</h3>
        <table>
          <thead>
            <tr>
              <th>Filter</th>
              <th>Exposure (s)</th>
              <th>Count</th>
              <th>Name</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {steps.map((s, i) => (
              <tr key={i}>
                <td>
                  <input
                    value={s.filter}
                    onChange={(e) => setStep(i, { filter: e.target.value })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    step="0.1"
                    value={s.exposure_s}
                    onChange={(e) => setStep(i, { exposure_s: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    type="number"
                    min={1}
                    value={s.count}
                    onChange={(e) => setStep(i, { count: Number(e.target.value) })}
                  />
                </td>
                <td>
                  <input
                    value={s.name ?? ""}
                    onChange={(e) => setStep(i, { name: e.target.value })}
                  />
                </td>
                <td>
                  <button type="button" onClick={() => removeStep(i)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          <button type="button" onClick={addStep}>
            Add step
          </button>
        </p>
        <h3>Dither</h3>
        <label>
          <input
            type="checkbox"
            checked={dither.enabled}
            onChange={(e) => setDither({ ...dither, enabled: e.target.checked })}
          />{" "}
          Enable
        </label>{" "}
        <label>
          pixels:{" "}
          <input
            type="number"
            min={1}
            value={dither.pixels}
            onChange={(e) => setDither({ ...dither, pixels: Number(e.target.value) })}
          />
        </label>{" "}
        <label>
          every N subs:{" "}
          <input
            type="number"
            min={1}
            value={dither.every_n_subs}
            onChange={(e) => setDither({ ...dither, every_n_subs: Number(e.target.value) })}
          />
        </label>
        {submit.error && (
          <p style={{ color: "var(--color-danger)" }}>{(submit.error as Error).message}</p>
        )}
      </Card>

      <Card title="Recent sequences">
        {recent.data?.length === 0 && <p>No sequences yet.</p>}
        {recent.data && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Status</th>
                <th>Subs</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {recent.data.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td>
                  <td>{s.name}</td>
                  <td>
                    <code>{s.status}</code>
                  </td>
                  <td>
                    {s.subs_completed}/{s.subs_total}
                  </td>
                  <td>
                    <Link to={`/sequences/${s.id}`}>open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
