import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useParams } from "react-router-dom";
import { sequencesApi } from "@/api/endpoints/sequences";
import { useEventStream } from "@/events/EventStream";
import { Card } from "@/ui/Card";
import { ConfirmButton } from "@/ui/ConfirmButton";
import { ProgressBar } from "@/ui/ProgressBar";

export function SequenceRunnerView() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const run = useQuery({
    queryKey: ["sequence", runId],
    queryFn: () => sequencesApi.get(runId),
    enabled: Number.isFinite(runId),
    refetchInterval: 5_000,
  });

  useEffect(() => {
    return subscribe("sequence", (e) => {
      const raw = e.payload && (e.payload as Record<string, unknown>)["run_id"];
      const target = typeof raw === "number" ? raw : typeof raw === "string" ? Number(raw) : NaN;
      if (Number.isFinite(target) && target === runId) {
        void qc.invalidateQueries({ queryKey: ["sequence", runId] });
      }
    });
  }, [subscribe, qc, runId]);

  const pause = useMutation({
    mutationFn: () => sequencesApi.pause(runId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sequence", runId] }),
  });
  const resume = useMutation({
    mutationFn: () => sequencesApi.resume(runId),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sequence", runId] }),
  });
  const abort = useMutation({
    mutationFn: () => sequencesApi.abort(runId, "user"),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["sequence", runId] }),
  });

  if (!Number.isFinite(runId)) return <p>Invalid sequence id.</p>;
  if (run.isLoading) return <p>Loading…</p>;
  if (run.error)
    return <p style={{ color: "var(--color-danger)" }}>{(run.error as Error).message}</p>;
  if (!run.data) return <p>Not found.</p>;
  const r = run.data;

  return (
    <div>
      <h1>
        Sequence #{r.id} — {r.name}
      </h1>
      <Card title="Status">
        <p>
          <code>{r.status}</code> {r.failure_reason && <>· {r.failure_reason}</>}
        </p>
        <ProgressBar value={r.subs_completed} total={r.subs_total} />
        <p>
          {r.subs_completed} / {r.subs_total} subs
          {r.current_step_index != null && <> · step {r.current_step_index + 1}</>}
          {r.current_sub_index != null && <> · sub {r.current_sub_index + 1}</>}
        </p>
        <p>
          <button
            type="button"
            disabled={r.status !== "RUNNING" || pause.isPending}
            onClick={() => pause.mutate()}
          >
            Pause
          </button>{" "}
          <button
            type="button"
            disabled={r.status !== "PAUSED" || resume.isPending}
            onClick={() => resume.mutate()}
          >
            Resume
          </button>{" "}
          <ConfirmButton
            label="Abort"
            confirmLabel="Confirm abort"
            onConfirm={() => abort.mutate()}
            danger
          />
        </p>
      </Card>

      {r.definition && (
        <Card title="Definition">
          <pre style={{ background: "var(--color-surface)", padding: 8, overflow: "auto" }}>
            {JSON.stringify(r.definition, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
