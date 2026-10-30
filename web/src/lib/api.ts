export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function setIndiProperty(
  device: string,
  name: string,
  values: Record<string, string | number | boolean>,
): Promise<void> {
  const url = `/api/indi/devices/${encodeURIComponent(device)}/properties/${encodeURIComponent(name)}`;
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values }),
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
    throw new ApiError(response.status, String(body.detail ?? response.statusText));
  }
}
