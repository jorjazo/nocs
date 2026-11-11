// Why a go to (or a go and centre) was refused, when the app has something to offer:
// "horizon" (go anyway) or "guiding" (PHD2 holds the mount: stop guiding for it, and
// perhaps guide again there; ADR 0023). Anything else is shown as it is.
export type GoRefusal = "horizon" | "guiding";

export function goRefusal(status: number, message: string): GoRefusal | null {
  if (status !== 409) return null;
  if (message.includes("below the horizon")) return "horizon";
  // A mount held for PHD2 is "mount is busy (guiding)": a job's would name the job.
  if (message.includes("busy (guiding)")) return "guiding";
  return null;
}
