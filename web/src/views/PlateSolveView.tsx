import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError } from "@/api/client";
import { imagesApi } from "@/api/endpoints/images";
import { plateSolvingApi } from "@/api/endpoints/platesolving";
import { useTopic } from "@/events/useTopic";
import { Card } from "@/ui/Card";

function formatSolveError(err: unknown): string {
  if (err instanceof ApiError && err.body && typeof err.body === "object") {
    const b = err.body as { failure_kind?: string; message?: string };
    if (b.failure_kind != null || b.message != null) {
      return [b.failure_kind, b.message].filter(Boolean).join(": ");
    }
  }
  return err instanceof Error ? err.message : String(err);
}

export function PlateSolveView() {
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ["plateInstallStatus"],
    queryFn: plateSolvingApi.installStatus,
  });
  const progress = useQuery({
    queryKey: ["plateInstallProgress"],
    queryFn: plateSolvingApi.installProgress,
    refetchInterval: 2000,
  });
  const images = useQuery({
    queryKey: ["images", { limit: 50 }],
    queryFn: () => imagesApi.list({ limit: 50, offset: 0 }),
  });
  useTopic("platesolving");
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: ["plateInstallStatus"] });
  }, [progress.data?.phase, qc]);

  const [imageId, setImageId] = useState<number | null>(null);
  const [accept, setAccept] = useState(false);

  const solve = useMutation({
    mutationFn: () => plateSolvingApi.solve({ image_id: imageId! }),
  });
  const install = useMutation({
    mutationFn: () => plateSolvingApi.startInstall(accept),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["plateInstallProgress"] });
    },
  });

  return (
    <div>
      <h1>Plate solving</h1>

      <Card title="ASTAP installation">
        {status.data && (
          <ul>
            <li>
              <b>Installed:</b> {status.data.installed ? "yes" : "no"}
            </li>
            <li>
              <b>DB present:</b> {status.data.db_present ? "yes" : "no"}
            </li>
            <li>
              <b>Binary:</b> <code>{status.data.binary_path ?? "—"}</code>
            </li>
            <li>
              <b>DB dir:</b> <code>{status.data.db_dir ?? "—"}</code>
            </li>
            <li>
              <b>DB:</b> {status.data.db_name}
            </li>
            <li>
              <b>Supported platform:</b> {status.data.supported_platform ? "yes" : "no"}
            </li>
            <li>
              <b>Network installs allowed:</b> {status.data.allow_network ? "yes" : "no"}
            </li>
          </ul>
        )}
        {!status.data?.db_present && status.data?.allow_network && (
          <>
            <label>
              <input
                type="checkbox"
                checked={accept}
                onChange={(e) => setAccept(e.target.checked)}
              />{" "}
              I accept the ASTAP license terms
            </label>
            <p>
              <button
                type="button"
                disabled={!accept || install.isPending}
                onClick={() => install.mutate()}
              >
                Fetch & install ASTAP + DB
              </button>
            </p>
          </>
        )}
        {progress.data && progress.data.phase !== "idle" && (
          <p>
            <code>{progress.data.phase}</code> — {progress.data.message}
            {progress.data.bytes_total > 0 &&
              ` (${progress.data.bytes_done}/${progress.data.bytes_total} bytes)`}
          </p>
        )}
        {install.error && (
          <p style={{ color: "var(--color-danger)" }}>{(install.error as Error).message}</p>
        )}
      </Card>

      <Card title="Solve a recent image">
        <label>
          Image:
          <select
            value={imageId ?? ""}
            onChange={(e) => setImageId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">— select —</option>
            {(images.data ?? []).map((i) => (
              <option key={i.id} value={i.id}>
                #{i.id} · {i.target} · {i.filter} · {i.exposureSec}s
              </option>
            ))}
          </select>
        </label>
        <p>
          <button
            type="button"
            disabled={!imageId || solve.isPending}
            onClick={() => solve.mutate()}
          >
            Solve
          </button>
        </p>
        {solve.data?.solved && solve.data.solution && (
          <pre>{JSON.stringify(solve.data.solution, null, 2)}</pre>
        )}
        {solve.isError && (
          <p style={{ color: "var(--color-danger)" }}>{formatSolveError(solve.error)}</p>
        )}
      </Card>
    </div>
  );
}
