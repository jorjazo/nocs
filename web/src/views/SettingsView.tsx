import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useState } from "react";
import { configApi } from "@/api/endpoints/config";
import { observatoriesApi, type CreateObservatoryBody } from "@/api/endpoints/observatories";
import { AuthContext } from "@/auth/AuthContext";
import { Card } from "@/ui/Card";

export function SettingsView() {
  const qc = useQueryClient();
  const { clearToken } = useContext(AuthContext);

  const config = useQuery({ queryKey: ["config"], queryFn: configApi.getAll });
  const observatories = useQuery({ queryKey: ["observatories"], queryFn: observatoriesApi.list });

  const patchConfig = useMutation({
    mutationFn: (body: Record<string, string>) => configApi.patch(body),
    onSuccess: (out) => qc.setQueryData(["config"], out),
  });
  const create = useMutation({
    mutationFn: (body: CreateObservatoryBody) => observatoriesApi.create(body),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["observatories"] }),
  });
  const activate = useMutation({
    mutationFn: (id: number) => observatoriesApi.activate(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["observatories"] }),
  });
  const remove = useMutation({
    mutationFn: (id: number) => observatoriesApi.delete(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["observatories"] }),
  });

  const [draft, setDraft] = useState<Record<string, string>>({});
  useEffect(() => {
    if (config.data) setDraft(config.data);
  }, [config.data]);

  const [obs, setObs] = useState<CreateObservatoryBody>({
    name: "",
    latitudeDeg: 0,
    longitudeDeg: 0,
    elevationM: 0,
    timezone: "UTC",
    horizonMaskJson: null,
  });

  return (
    <div>
      <h1>Settings</h1>
      <Card title="Bearer token">
        <p>
          Token is stored in the browser <code>localStorage</code>. Sign out clears it.
        </p>
        <button type="button" onClick={clearToken}>
          Sign out and re-enter token
        </button>
      </Card>

      <Card
        title="Configuration (config_kv)"
        actions={
          <button
            type="button"
            disabled={patchConfig.isPending || !config.data}
            onClick={() => patchConfig.mutate(draft)}
          >
            Save
          </button>
        }
      >
        {config.isLoading && <p>Loading…</p>}
        {config.data && (
          <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 8 }}>
            {Object.keys(draft)
              .sort()
              .map((k) => (
                <label key={k} style={{ display: "contents" }}>
                  <code>{k}</code>
                  <input
                    value={draft[k]}
                    onChange={(e) => setDraft((s) => ({ ...s, [k]: e.target.value }))}
                  />
                </label>
              ))}
          </div>
        )}
        {patchConfig.error && (
          <p style={{ color: "var(--color-danger)" }}>{(patchConfig.error as Error).message}</p>
        )}
      </Card>

      <Card title="Observatories">
        {observatories.isLoading && <p>Loading…</p>}
        {observatories.data && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Elev (m)</th>
                <th>TZ</th>
                <th>Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {observatories.data.map((o) => (
                <tr key={o.id}>
                  <td>{o.name}</td>
                  <td>{o.latitudeDeg.toFixed(4)}</td>
                  <td>{o.longitudeDeg.toFixed(4)}</td>
                  <td>{o.elevationM}</td>
                  <td>{o.timezone}</td>
                  <td>{o.active ? "yes" : ""}</td>
                  <td>
                    {!o.active && (
                      <button type="button" onClick={() => activate.mutate(o.id)}>
                        Activate
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => remove.mutate(o.id)}
                      style={{ marginLeft: 8 }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <h3>Add observatory</h3>
        <div style={{ display: "grid", gridTemplateColumns: "120px 1fr", gap: 8 }}>
          <label style={{ display: "contents" }}>
            <span>Name</span>
            <input value={obs.name} onChange={(e) => setObs({ ...obs, name: e.target.value })} />
          </label>
          <label style={{ display: "contents" }}>
            <span>Latitude (°)</span>
            <input
              type="number"
              value={obs.latitudeDeg}
              onChange={(e) => setObs({ ...obs, latitudeDeg: Number(e.target.value) })}
            />
          </label>
          <label style={{ display: "contents" }}>
            <span>Longitude (°)</span>
            <input
              type="number"
              value={obs.longitudeDeg}
              onChange={(e) => setObs({ ...obs, longitudeDeg: Number(e.target.value) })}
            />
          </label>
          <label style={{ display: "contents" }}>
            <span>Elevation (m)</span>
            <input
              type="number"
              value={obs.elevationM}
              onChange={(e) => setObs({ ...obs, elevationM: Number(e.target.value) })}
            />
          </label>
          <label style={{ display: "contents" }}>
            <span>Timezone</span>
            <input
              value={obs.timezone}
              onChange={(e) => setObs({ ...obs, timezone: e.target.value })}
            />
          </label>
        </div>
        <p>
          <button
            type="button"
            disabled={create.isPending || !obs.name}
            onClick={() => create.mutate(obs)}
          >
            Add
          </button>
        </p>
      </Card>
    </div>
  );
}
