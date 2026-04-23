import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { targetsApi } from "@/api/endpoints/targets";
import { devicesApi } from "@/api/endpoints/devices";
import { Card } from "@/ui/Card";
import type { TargetSearchResult } from "@/api/types";

export function TargetsView() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [submitted, setSubmitted] = useState<string | null>(null);
  const [selected, setSelected] = useState<TargetSearchResult | null>(null);
  const [mountId, setMountId] = useState("");

  const devices = useQuery({ queryKey: ["devices"], queryFn: devicesApi.list });
  const search = useQuery({
    queryKey: ["targets", "search", submitted],
    queryFn: () => targetsApi.search(submitted!),
    enabled: !!submitted,
  });

  const slew = useMutation({
    mutationFn: (args: { id: string; ra: number; dec: number }) =>
      devicesApi.slew(args.id, { raHours: args.ra, decDegrees: args.dec }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const sync = useMutation({
    mutationFn: (args: { id: string; ra: number; dec: number }) =>
      devicesApi.sync(args.id, { raHours: args.ra, decDegrees: args.dec }),
  });

  return (
    <div>
      <h1>Targets</h1>
      <Card title="Search">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSubmitted(q.trim());
          }}
          style={{ display: "flex", gap: 8 }}
        >
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="M31, NGC 7000, Vega…"
            autoFocus
            style={{ flex: 1 }}
          />
          <button type="submit">Search</button>
        </form>
        {search.isLoading && <p>Loading…</p>}
        {search.error && (
          <p style={{ color: "var(--color-danger)" }}>{(search.error as Error).message}</p>
        )}
        {search.data && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Kind</th>
                <th>Mag</th>
                <th>RA (h)</th>
                <th>Dec (°)</th>
              </tr>
            </thead>
            <tbody>
              {search.data.map((r) => (
                <tr
                  key={r.target.id}
                  onClick={() => setSelected(r)}
                  style={{
                    cursor: "pointer",
                    background:
                      selected?.target.id === r.target.id ? "var(--color-surface-2)" : undefined,
                  }}
                >
                  <td>
                    <code>{r.target.id}</code>
                  </td>
                  <td>{r.target.primaryName}</td>
                  <td>{r.target.kind}</td>
                  <td>
                    {Number.isFinite(r.target.magnitude) ? r.target.magnitude.toFixed(2) : "—"}
                  </td>
                  <td>{(r.target.raJ2000Deg / 15).toFixed(3)}</td>
                  <td>{r.target.decJ2000Deg.toFixed(3)}</td>
                </tr>
              ))}
              {search.data.length === 0 && (
                <tr>
                  <td colSpan={6} style={{ color: "var(--color-text-muted)" }}>
                    No matches.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </Card>

      {selected && (
        <Card title={`Details: ${selected.target.primaryName}`}>
          <table>
            <tbody>
              <tr>
                <th>RA (J2000)</th>
                <td>{(selected.target.raJ2000Deg / 15).toFixed(4)} h</td>
              </tr>
              <tr>
                <th>Dec (J2000)</th>
                <td>{selected.target.decJ2000Deg.toFixed(4)} °</td>
              </tr>
              <tr>
                <th>Constellation</th>
                <td>{selected.target.constellation || "—"}</td>
              </tr>
              <tr>
                <th>Notes</th>
                <td>{selected.target.notes || "—"}</td>
              </tr>
              {selected.observation && (
                <>
                  <tr>
                    <th>Altitude</th>
                    <td>{selected.observation.altitudeDeg.toFixed(2)} °</td>
                  </tr>
                  <tr>
                    <th>Azimuth</th>
                    <td>{selected.observation.azimuthDeg.toFixed(2)} °</td>
                  </tr>
                  <tr>
                    <th>Airmass</th>
                    <td>{selected.observation.airmass.toFixed(3)}</td>
                  </tr>
                  <tr>
                    <th>Hour angle</th>
                    <td>{selected.observation.hourAngleHours.toFixed(3)} h</td>
                  </tr>
                  <tr>
                    <th>Time to transit</th>
                    <td>
                      {selected.observation.transitInHours == null
                        ? "—"
                        : `${selected.observation.transitInHours.toFixed(2)} h`}
                    </td>
                  </tr>
                </>
              )}
            </tbody>
          </table>
          <div style={{ marginTop: 12, display: "flex", gap: 8, alignItems: "center" }}>
            <label>
              Mount:&nbsp;
              <select value={mountId} onChange={(e) => setMountId(e.target.value)}>
                <option value="">— select —</option>
                {(devices.data ?? [])
                  .filter((d) => d.kind === "mount")
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.id}
                    </option>
                  ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!mountId || slew.isPending}
              onClick={() =>
                slew.mutate({
                  id: mountId,
                  ra: selected.target.raJ2000Deg / 15,
                  dec: selected.target.decJ2000Deg,
                })
              }
            >
              Slew
            </button>
            <button
              type="button"
              disabled={!mountId || sync.isPending}
              onClick={() =>
                sync.mutate({
                  id: mountId,
                  ra: selected.target.raJ2000Deg / 15,
                  dec: selected.target.decJ2000Deg,
                })
              }
            >
              Sync
            </button>
          </div>
          {slew.error && (
            <p style={{ color: "var(--color-danger)" }}>{(slew.error as Error).message}</p>
          )}
        </Card>
      )}
    </div>
  );
}
