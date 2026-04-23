import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { sessionsApi } from "@/api/endpoints/sessions";
import { Card } from "@/ui/Card";

export function SessionsView() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const params = useParams<{ id?: string }>();
  const sessionId = params.id != null && params.id !== "" ? Number(params.id) : null;

  const list = useQuery({ queryKey: ["sessions"], queryFn: sessionsApi.list });
  const detail = useQuery({
    queryKey: ["session", sessionId],
    queryFn: () => sessionsApi.get(sessionId!),
    enabled: sessionId != null && Number.isFinite(sessionId),
  });
  const [name, setName] = useState("");
  const open = useMutation({
    mutationFn: () => sessionsApi.open(name || "session"),
    onSuccess: (s) => {
      void qc.invalidateQueries({ queryKey: ["sessions"] });
      navigate(`/sessions/${s.id}`);
    },
  });
  const close = useMutation({
    mutationFn: (id: number) => sessionsApi.close(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sessions"] }),
  });

  return (
    <div>
      <h1>Sessions</h1>

      <Card title="Open new session">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="name" />{" "}
        <button type="button" onClick={() => open.mutate()}>
          Open
        </button>
      </Card>

      <Card title="All sessions">
        {list.isLoading && <p>Loading…</p>}
        {list.data && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Opened</th>
                <th>Closed</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {list.data.map((s) => (
                <tr key={s.id}>
                  <td>#{s.id}</td>
                  <td>{s.name}</td>
                  <td>{s.opened_at}</td>
                  <td>{s.closed_at ?? "—"}</td>
                  <td>
                    <button type="button" onClick={() => navigate(`/sessions/${s.id}`)}>
                      open
                    </button>{" "}
                    {!s.closed_at && (
                      <button type="button" onClick={() => close.mutate(s.id)}>
                        close
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {sessionId != null && Number.isFinite(sessionId) && detail.data && (
        <Card title={`Events for #${sessionId}`}>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>ts</th>
                <th>Topic</th>
                <th>Type</th>
                <th>Payload</th>
              </tr>
            </thead>
            <tbody>
              {detail.data.events.map((e) => (
                <tr key={e.id}>
                  <td>#{e.id}</td>
                  <td>{e.ts}</td>
                  <td>
                    <code>{e.topic}</code>
                  </td>
                  <td>{e.type}</td>
                  <td>
                    <code style={{ whiteSpace: "pre-wrap" }}>{e.payload_json ?? ""}</code>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}
