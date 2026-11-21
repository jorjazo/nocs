// The Video view's arithmetic (lucky imaging): regions of interest, how much a
// recording takes, and what a frame on screen means on the sensor.

import type { Region } from "./types.ts";

export type RegionSize = { width: number; height: number };

// Common sizes for planets, the Moon's craters or a sunspot; only those smaller
// than the sensor are offered, besides the whole of it.
export const REGION_SIZES: readonly RegionSize[] = [
  { width: 320, height: 240 },
  { width: 640, height: 480 },
  { width: 1024, height: 768 },
  { width: 1920, height: 1080 },
];

export function regionSizes(sensor: RegionSize): RegionSize[] {
  return REGION_SIZES.filter((size) => size.width < sensor.width && size.height < sensor.height);
}

// A region of `size` centred on `x`, `y` (sensor pixels), inside the sensor, at even
// coordinates (the server fits it to the camera's rules too).
export function regionAt(x: number, y: number, size: RegionSize, sensor: RegionSize): Region {
  const width = Math.min(size.width, sensor.width);
  const height = Math.min(size.height, sensor.height);
  const left = Math.min(Math.max(0, Math.round(x - width / 2)), sensor.width - width);
  const top = Math.min(Math.max(0, Math.round(y - height / 2)), sensor.height - height);
  return { x: left - (left % 2), y: top - (top % 2), width, height };
}

// Where a point of the image on screen (0..1 across and down) lies on the sensor:
// the image is the region when one is read out, else the whole sensor.
export function sensorPoint(
  point: { x: number; y: number },
  region: Region | null,
  sensor: RegionSize,
): { x: number; y: number } {
  const frame = region ?? { x: 0, y: 0, width: sensor.width, height: sensor.height };
  return { x: frame.x + point.x * frame.width, y: frame.y + point.y * frame.height };
}

// The size the region would take: the same as the one read out, or a preset.
export function sameSize(region: Region | null, size: RegionSize): boolean {
  return region !== null && region.width === size.width && region.height === size.height;
}

// Bytes of one recorded frame (raw, one channel: mono or Bayer).
export function frameBytes(width: number, height: number, depth: number): number {
  return width * height * (depth > 8 ? 2 : 1);
}

export type Length = { mode: "seconds"; value: number } | { mode: "frames"; value: number };

// What a recording of `length` will take at `fps`, with the SER header and its
// timestamps.
export function recordingBytes(length: Length, bytes: number, fps: number | null): number | null {
  const frames = length.mode === "frames" ? length.value : fps === null ? null : length.value * fps;
  if (frames === null) return null;
  return Math.round(178 + frames * (bytes + 8));
}

// Frames a recording lacks, as a share of what the camera sent; null when unknown.
export function droppedShare(frames: number, dropped: number | null): number | null {
  if (dropped === null || frames + dropped === 0) return null;
  return dropped / (frames + dropped);
}
