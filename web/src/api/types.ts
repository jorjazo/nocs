export type DeviceKind = "mount" | "camera" | "filterwheel" | "focuser" | "unknown";

export interface DeviceView {
  id: string;
  indiName: string;
  kind: DeviceKind;
  state: string;
  connected: boolean;
}

export interface SlewBody {
  raHours: number;
  decDegrees: number;
}
export interface CoolBody {
  setpointCelsius: number;
}
export interface ExposeBody {
  durationSeconds: number;
  filter?: string;
  target?: string;
  step?: string;
  seq?: number;
}
export interface MoveBody {
  position?: number;
  offset?: number;
}
export interface SelectSlotBody {
  slot: number;
}

export interface TargetView {
  id: string;
  primaryName: string;
  aliases: string[];
  kind: string;
  raJ2000Deg: number;
  decJ2000Deg: number;
  constellation: string;
  magnitude: number;
  sizeArcmin: number;
  notes: string;
}

export interface TargetObservation {
  altitudeDeg: number;
  azimuthDeg: number;
  airmass: number;
  hourAngleHours: number;
  transitInHours: number | null;
}

export interface TargetSearchResult {
  target: TargetView;
  observation: TargetObservation | null;
}

export interface ImageView {
  id: number;
  sessionId: number | null;
  device: string;
  filter: string;
  target: string;
  exposureSec: number;
  step: string;
  seq: number;
  fitsPath: string;
  thumbPath: string | null;
  bytes: number;
  width: number | null;
  height: number | null;
  bitpix: number | null;
  dateObs: string | null;
  createdAt: string;
}

export interface ObservatoryView {
  id: number;
  name: string;
  latitudeDeg: number;
  longitudeDeg: number;
  elevationM: number;
  timezone: string;
  horizonMaskJson: string | null;
  active: boolean;
}

export interface RuleView {
  name: string;
  action: "pause_sequence" | "abort_and_park" | "e_stop";
  when: Record<string, unknown>;
  latched: boolean;
}

export interface SafetyStatusView {
  rules: RuleView[];
  latched: string[];
  activeTargetId: string | null;
}

export interface InstallStatusView {
  installed: boolean;
  binary_path: string | null;
  db_dir: string | null;
  db_name: string;
  /** Star DB and binary layout OK for solving */
  db_present: boolean;
  supported_platform: boolean;
  allow_network: boolean;
}

export interface InstallProgressView {
  phase: string;
  message: string;
  bytes_done: number;
  bytes_total: number;
  updated_at: string;
}

export interface PlateSolutionView {
  ra_j2000_deg: number;
  dec_j2000_deg: number;
  pixel_scale_arcsec_per_pixel: number;
  rotation_deg: number;
  field_width_deg: number;
  field_height_deg: number;
  solver: string;
  solved_at: string;
  duration_ms: number;
}

export interface SolveResponse {
  solved: boolean;
  image_id: number;
  failure_kind?: string;
  message?: string;
  duration_ms: number;
  solution?: PlateSolutionView;
}

export type SequenceStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED" | "ABORTED" | "FAILED";

export interface SequenceStepDto {
  filter: string;
  exposure_s: number;
  count: number;
  name?: string;
}

export interface PreStepDto {
  type: "slew_and_sync" | "autofocus";
}

export interface DitherDto {
  enabled: boolean;
  pixels: number;
  every_n_subs: number;
}

export interface DeviceIdsDto {
  mount_id?: string;
  camera_id?: string;
  filter_wheel_id?: string;
  focuser_id?: string;
}

export interface SequenceDefinitionDto {
  name?: string;
  target_id?: string;
  dither?: DitherDto;
  pre_steps?: PreStepDto[];
  steps?: SequenceStepDto[];
  device_ids?: DeviceIdsDto;
}

export interface SequenceView {
  id: number;
  session_id: number | null;
  name: string;
  status: SequenceStatus;
  failure_reason: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  current_step_index: number | null;
  current_sub_index: number | null;
  subs_completed: number;
  subs_total: number;
  definition: SequenceDefinitionDto | null;
}

export interface SessionRow {
  id: number;
  name: string;
  opened_at: string;
  closed_at: string | null;
}

/** JSON from POST /api/sessions (Java `Session` record). */
export interface SessionCreated {
  id: number;
  name: string;
  openedAt: string;
  closedAt: string | null;
  logPath: string;
}

export interface SessionEventRow {
  id: number;
  ts: string;
  topic: string;
  type: string;
  payload_json: string | null;
}

export interface SessionDetail {
  session: SessionRow;
  events: SessionEventRow[];
}

export type EventTopic =
  | "mount"
  | "camera"
  | "filterwheel"
  | "focuser"
  | "sequence"
  | "safety"
  | "session"
  | "device_connection"
  | "system"
  | "target"
  | "sensor"
  | "platesolving";

export interface BusEvent<T = Record<string, unknown>> {
  topic: EventTopic;
  type: string;
  ts: string;
  payload?: T;
}
