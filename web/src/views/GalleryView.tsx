import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getToken } from "@/api/token";
import { imagesApi, type ImageListFilters } from "@/api/endpoints/images";
import { useEventStream } from "@/events/EventStream";
import { Card } from "@/ui/Card";

export function GalleryView() {
  const qc = useQueryClient();
  const { subscribe } = useEventStream();
  const [filters, setFilters] = useState<ImageListFilters>({ limit: 100, offset: 0 });

  const list = useQuery({
    queryKey: ["images", filters],
    queryFn: () => imagesApi.list(filters),
  });

  const remove = useMutation({
    mutationFn: (id: number) => imagesApi.delete(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["images"] }),
  });

  useEffect(() => {
    return subscribe("camera", () => {
      void qc.invalidateQueries({ queryKey: ["images"] });
    });
  }, [subscribe, qc]);

  const token = getToken();

  return (
    <div>
      <h1>Gallery</h1>
      <Card title="Filters">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <label>
            Device{" "}
            <input
              value={filters.device ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, device: e.target.value }))}
            />
          </label>
          <label>
            Target{" "}
            <input
              value={filters.target ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, target: e.target.value }))}
            />
          </label>
          <label>
            Filter{" "}
            <input
              value={filters.filter ?? ""}
              onChange={(e) => setFilters((f) => ({ ...f, filter: e.target.value }))}
            />
          </label>
          <button type="button" onClick={() => void qc.invalidateQueries({ queryKey: ["images"] })}>
            Refresh
          </button>
        </div>
      </Card>

      <Card title={`Images (${list.data?.length ?? 0})`}>
        {list.isLoading && <p>Loading…</p>}
        {list.data?.length === 0 && <p>No images yet.</p>}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
            gap: 12,
          }}
        >
          {(list.data ?? []).map((img) => (
            <article
              key={img.id}
              style={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                borderRadius: 6,
                padding: 8,
              }}
            >
              <img
                src={`/api/images/${img.id}/thumb.jpg?token=${encodeURIComponent(token ?? "")}`}
                alt={`#${img.id}`}
                style={{ width: "100%", height: 160, objectFit: "cover", background: "#000" }}
                loading="lazy"
              />
              <div style={{ fontSize: 12, marginTop: 6 }}>
                #{img.id} · {img.target} · {img.filter} · {img.exposureSec}s
                <br />
                <code>{img.device}</code> · seq {img.seq}
              </div>
              <div style={{ marginTop: 6, display: "flex", gap: 6 }}>
                <button
                  type="button"
                  onClick={() => void imagesApi.downloadFits(img.id, `image-${img.id}.fits`)}
                >
                  FITS
                </button>
                <button type="button" onClick={() => remove.mutate(img.id)}>
                  Delete
                </button>
              </div>
            </article>
          ))}
        </div>
      </Card>
    </div>
  );
}
