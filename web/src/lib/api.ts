import type { JobStarted } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function post(url: string, body?: unknown): Promise<unknown> {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new ApiError(response.status, String(body.detail ?? response.statusText));
  }
  return response.status === 204 ? null : ((await response.json()) as unknown);
}

export async function setIndiProperty(
  device: string,
  name: string,
  values: Record<string, string | number | boolean>,
): Promise<void> {
  const url = `/api/indi/devices/${encodeURIComponent(device)}/properties/${encodeURIComponent(name)}`;
  await post(url, { values });
}

export async function connectProfile(profile: string): Promise<void> {
  await post("/api/equipment/connect", { profile });
}

export async function disconnectEquipment(): Promise<void> {
  await post("/api/equipment/disconnect");
}

export async function expose(role: string, exposure: number): Promise<string> {
  const started = (await post(`/api/cameras/${role}/expose`, { exposure })) as JobStarted;
  return started.job;
}

export async function loop(role: string, exposure: number): Promise<string> {
  const started = (await post(`/api/cameras/${role}/loop`, { exposure })) as JobStarted;
  return started.job;
}

export async function cancelJob(job: string): Promise<void> {
  await post(`/api/jobs/${job}/cancel`);
}
