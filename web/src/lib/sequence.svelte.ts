// The sequence the Sequences view shows and edits: the running one, or the one this
// device chose last, kept as a draft saved a moment after each change; and the words
// for a template, its groups and its steps.

import { deleteSequence, listSequences, saveTemplate } from "./api";
import { formatDecimal, formatDuration, formatPlain, formatSeconds, formatTemperature, formatTime } from "./format";
import type { Messages } from "./i18n";
import type { AutofocusTrigger, DitherTrigger, FlipTrigger, RecenterTrigger } from "./generated/api";
import { focusReason, freeId, newTemplate, triggerDue, type CameraSettings } from "./sequence";
import type { Container, Group, Node, PowerOutput, Sequence, SequenceEvent, SequenceRun, Template } from "./types";

export { isActive, sequenceId } from "./sequence";

const SELECTED = "nocs.sequence.selected";
const SAVE_AFTER = 600;

function read(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked (private mode)
  }
}

function write(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Not kept; the choice holds until the page reloads.
  }
}

class Sequences {
  // Every saved sequence, by id.
  all: Record<string, Sequence> = $state({});
  loaded = $state(false);
  loading = $state(false);
  id: string | null = $state(read(SELECTED));
  draft: Template | null = $state(null);
  error = $state("");
  saving = $state(false);
  // What was last saved or loaded, to tell unsaved changes.
  private saved = "";
  private timer: ReturnType<typeof setTimeout> | null = null;

  get dirty(): boolean {
    return this.draft !== null && JSON.stringify(this.draft) !== this.saved;
  }

  // Load the saved sequences and show `prefer` (the running one), the one chosen last,
  // or the first. A draft with unsaved changes is kept.
  async load(prefer: string | null = null): Promise<void> {
    this.loading = true;
    try {
      this.all = await listSequences();
      this.loaded = true;
      const ids = Object.keys(this.all).filter((id) => this.all[id]?.template);
      const pick = [prefer, this.id].find((id): id is string => !!id && ids.includes(id)) ?? ids[0] ?? null;
      if (pick !== this.id || !this.draft || !this.dirty) this.show(pick);
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.loading = false;
    }
  }

  // Show another saved sequence (unsaved changes to this one are saved first).
  show(id: string | null): void {
    this.flush();
    this.id = id;
    if (id) write(SELECTED, id);
    const template = id ? this.all[id]?.template : null;
    this.draft = template ? structuredClone($state.snapshot(template)) : null;
    this.saved = this.draft ? JSON.stringify(this.draft) : "";
  }

  // A new sequence, saved at once, and shown.
  async create(name: string, filter: string | null, guide: boolean, solver: boolean, camera: CameraSettings): Promise<void> {
    this.flush();
    const id = freeId(name, Object.keys(this.all));
    const template = newTemplate(name, filter, guide, solver, camera);
    await saveTemplate(id, template);
    this.all = { ...this.all, [id]: { name, template } as Sequence };
    this.show(id);
    await this.load(id);
  }

  async remove(id: string): Promise<void> {
    await deleteSequence(id);
    const { [id]: _, ...rest } = this.all;
    this.all = rest;
    if (this.id === id) {
      this.id = null;
      this.draft = null;
      this.saved = "";
    }
    await this.load();
  }

  // Called after every change of the draft: saved a moment later.
  changed(): void {
    if (!this.dirty) return;
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => void this.save(), SAVE_AFTER);
  }

  // Save now what is waiting.
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
      void this.save();
    }
  }

  async save(): Promise<void> {
    this.timer = null;
    const id = this.id;
    const draft = this.draft;
    if (!id || !draft || !this.dirty) return;
    const body = $state.snapshot(draft);
    const text = JSON.stringify(body);
    this.saving = true;
    try {
      await saveTemplate(id, body);
      // Another sequence may be shown by now: its own draft stays as it is.
      if (this.id === id) this.saved = text;
      this.all = { ...this.all, [id]: { ...(this.all[id] ?? {}), name: body.name, template: body } as Sequence };
      this.error = "";
    } catch (e) {
      this.error = e instanceof Error ? e.message : String(e);
    } finally {
      this.saving = false;
    }
  }
}

export const sequences = new Sequences();

// -- Words for a template, its groups and the steps it makes ----------------------

export function windowSummary(template: Template, t: Messages, locale: string): string {
  const s = t.sequence;
  const parts = [
    template.start_at_dusk !== false ? s.fromDusk(s.darkness[template.darkness ?? "astronomical"]) : s.fromNow,
    template.until_dawn !== false ? s.untilDawn : s.untilDone,
  ];
  if (template.min_altitude != null) parts.push(s.above(formatPlain(template.min_altitude, locale)));
  return parts.join(" · ");
}

export function focusSummary(template: Template, t: Messages, locale: string): string {
  const s = t.sequence;
  const focus = template.focus;
  if (!focus) return s.off;
  const reasons: string[] = [];
  if (focus.at_start !== false) reasons.push(s.focusAtStart);
  if (focus.filter_change) reasons.push(s.focusFilter);
  if (focus.temperature_change != null) reasons.push(s.focusTemperature(formatPlain(focus.temperature_change, locale)));
  if (focus.hfr_increase != null) reasons.push(s.focusHfr(formatPlain(focus.hfr_increase * 100, locale)));
  if (focus.minutes != null) reasons.push(s.focusMinutes(formatPlain(focus.minutes, locale)));
  return reasons.length ? capitalize(reasons.join(" · ")) : s.off;
}

export function pointingSummary(template: Template, t: Messages, locale: string): string {
  const s = t.sequence;
  if (!template.center) return s.pointingOff;
  if (template.recenter_every != null) {
    return s.pointingCheck(template.recenter_every, formatPlain(template.recenter_drift ?? 2, locale));
  }
  return s.pointingCenter;
}

export function coolingSummary(template: Template, t: Messages, locale: string): string {
  const s = t.sequence;
  switch (template.cooling ?? "off") {
    case "global":
      return template.temperature != null ? formatTemperature(template.temperature, locale, 0) : s.off;
    case "group":
      return s.coolingPerGroup;
    default:
      return s.off;
  }
}

export function endSummary(template: Template, t: Messages, outputs: PowerOutput[]): string {
  const s = t.sequence;
  const end = template.end ?? { park: true, warm: true, outputs: [] };
  const parts: string[] = [];
  if (end.park !== false) parts.push(s.park);
  if (end.warm !== false) parts.push(s.warm);
  if (end.outputs?.length) parts.push(s.outputsOff(outputLabels(end.outputs, outputs)));
  return parts.length ? capitalize(parts.join(" · ")) : s.nothing;
}

export function outputLabels(ids: string[], outputs: PowerOutput[]): string {
  return ids.map((id) => outputs.find((o) => o.id === id)?.label || id).join(", ");
}

// "L", "Dark", "Flat Ha": what a group is.
export function groupName(group: Group, t: Messages): string {
  const kind = group.frame_type ?? "light";
  if (kind === "light") return group.filter || t.sequence.noFilter;
  const name = t.sequence.kinds[kind];
  return kind === "flat" && group.filter ? `${name} ${group.filter}` : name;
}

// "20 × 120 s", "50 × shortest", "20 × found".
export function groupFrames(group: Group, t: Messages, locale: string): string {
  const s = t.sequence;
  if (group.frame_type === "bias") return s.frames(group.count, s.shortest);
  if (group.exposure == null) return s.frames(group.count, s.found);
  return s.frames(group.count, formatSeconds(group.exposure, locale));
}

// "gain 100 · offset 10 · 2×2 · −10 °C"; parts left out stand as the camera has them.
export function groupSettings(group: Group, template: Template, t: Messages, locale: string): string {
  const s = t.sequence;
  const parts = [s.rowSettings(group.gain == null ? null : formatPlain(group.gain, locale), group.offset == null ? null : formatPlain(group.offset, locale))];
  if (group.binning && group.binning > 1) parts.push(`${group.binning}×${group.binning}`);
  if (template.cooling === "group" && group.temperature != null) parts.push(formatTemperature(group.temperature, locale, 0));
  return parts.join(" · ");
}

export function describeNode(node: Node, t: Messages, locale: string, outputs: PowerOutput[]): string {
  const n = t.sequence.node;
  switch (node.kind) {
    case "cool":
      return n.cool(formatTemperature(node.temperature, locale, 0));
    case "warm":
      return n.warm;
    case "unpark":
      return n.unpark;
    case "park":
      return n.park;
    case "slew":
      return n.slew;
    case "filter":
      return n.filter(node.filter);
    case "autofocus":
      return n.autofocus;
    case "guide":
      return node.on ? n.guideOn : n.guideOff;
    case "dither":
      return n.dither;
    case "center":
      return n.center;
    case "recenter":
      return n.recenter;
    case "flip":
      return n.flip;
    case "aim":
      return n.aim;
    case "flats":
      return n.flats(node.filter ?? t.sequence.noFilter, node.count);
    case "prompt":
      return n.prompt(t.sequence.prompt[node.frame_type === "bias" ? "dark" : node.frame_type].title);
    case "outputs":
      return n.outputs(outputLabels(node.outputs, outputs), node.on);
    case "wait":
      if (node.time) return n.waitTime(formatTime(node.time, locale));
      if (node.dusk) return n.waitDusk(t.sequence.darkness[node.dusk]);
      return n.waitAltitude(formatPlain(node.altitude ?? 0, locale));
    case "expose":
      return n.expose(node.rows.reduce((sum, row) => sum + row.count, 0));
    default:
      if (!("children" in node)) return "";
      // The template names the container that holds while the target is up.
      if (node.name === "imaging") return n.imaging;
      if (node.name === "lights") return n.lights;
      if (node.name === "dark" || node.name === "bias" || node.name === "flat") return t.sequence.kinds[node.name];
      return node.name || node.target?.name || "";
  }
}

// What keeps a container going and what it watches: "until astronomical dawn · autofocus every 1 °C".
export function describeContainer(container: Container, t: Messages, locale: string): string {
  const n = t.sequence.node;
  const parts: string[] = [];
  if (container.repeat === null) parts.push(n.repeatForever);
  else if (container.repeat !== undefined && container.repeat > 1) parts.push(n.repeat(container.repeat));
  for (const condition of container.conditions ?? []) {
    if (condition.kind === "until_time") parts.push(n.untilTime(formatTime(condition.time, locale)));
    else if (condition.kind === "until_dawn") parts.push(n.untilDawn(t.sequence.darkness[condition.darkness ?? "astronomical"]));
    else if ("altitude" in condition) parts.push(n.whileAbove(formatPlain(condition.altitude ?? 30, locale)));
  }
  for (const each of container.triggers ?? []) {
    const s = t.sequence;
    if (each.kind === "dither") {
      parts.push(n.ditherEvery((each as DitherTrigger).every ?? 1));
      continue;
    }
    if (each.kind === "flip") {
      parts.push(n.flipAfter(formatPlain((each as FlipTrigger).after ?? 5, locale)));
      continue;
    }
    if (each.kind === "recenter") {
      parts.push(n.recenterEvery((each as RecenterTrigger).every ?? 10));
      continue;
    }
    const trigger = each as AutofocusTrigger;
    const reasons: string[] = [];
    if (trigger.filter_change) reasons.push(s.focusFilter);
    if (trigger.temperature_change != null) reasons.push(s.focusTemperature(formatPlain(trigger.temperature_change, locale)));
    if (trigger.hfr_increase != null) reasons.push(s.focusHfr(formatPlain(trigger.hfr_increase * 100, locale)));
    if (trigger.minutes != null) reasons.push(s.focusMinutes(formatPlain(trigger.minutes, locale)));
    if (trigger.frames != null) reasons.push(`${trigger.frames}`);
    parts.push(n.trigger(reasons.join(", ")));
  }
  return parts.join(" · ");
}

function capitalize(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// Why an autofocus was due, in the reader's words (the runner says it in English).
export function describeFocusReason(reason: string, t: Messages, locale: string): string {
  const r = t.session.event.focusReason;
  const why = focusReason(reason);
  switch (why.why) {
    case "filter":
      return r.filter(why.filter);
    case "temperature":
      return r.temperature(`${why.change > 0 ? "+" : ""}${formatTemperature(why.change, locale)}`);
    case "minutes":
      return r.minutes(why.minutes);
    case "frames":
      return r.frames(why.frames);
    case "hfr":
      return r.hfr(formatPlain(Math.abs(why.percent), locale));
    default:
      return why.text;
  }
}

function promptKind(value: unknown): "light" | "dark" | "flat" {
  return value === "dark" || value === "bias" ? "dark" : value === "flat" ? "flat" : "light";
}

// One line of the session's timeline, from the event's kind and data (the
// server's messages are English).
export function describeEvent(event: SequenceEvent, t: Messages, locale: string): string {
  const e = t.session.event;
  const n = t.sequence.node;
  const data = event.data as Record<string, unknown>;
  const number = (key: string): number | null => (typeof data[key] === "number" ? data[key] : null);
  switch (event.kind) {
    case "started":
      return e.started;
    case "resumed_after_restart":
      return e.resumed_after_restart;
    case "paused":
      return e.paused;
    case "resumed":
      return e.resumed;
    case "ending":
      return e.ending;
    case "prompt":
      return e.prompt(t.sequence.prompt[promptKind(data.frame_type ?? event.message)].title);
    case "ended": {
      const outcome = event.message as keyof typeof t.session.states;
      const ended = e.ended(t.session.states[outcome] ?? event.message);
      return typeof data.error === "string" ? `${ended} · ${data.error}` : ended;
    }
    case "failed":
      return e.failed(event.message);
    case "recovery":
      return data.guard ? e.guard : e.recovery(event.message);
    case "recovered": {
      const kind = String(data.kind ?? event.message) as keyof typeof e.failureKind;
      return e.recovered(e.failureKind[kind] ?? kind, number("failures") ?? 1);
    }
    case "skipped":
      return e.skipped(event.message);
    case "trigger": {
      const due = triggerDue(event.message);
      switch (due.kind) {
        case "flip":
          return due.waiting === null ? e.flipDue : e.flipWaiting(formatDecimal(due.waiting, locale, 1));
        case "autofocus":
          return e.focusDue(describeFocusReason(due.reason, t, locale));
        case "dither":
          return e.ditherDue(due.frames);
        case "recenter":
          return e.recenterDue(due.frames);
        default:
          return due.message;
      }
    }
    case "condition": {
      const condition = data.condition as keyof typeof e.condition;
      return e.condition[condition] ?? event.message;
    }
    case "frame": {
      const parts = [e.frame(event.message)];
      const hfr = number("hfr");
      const stars = number("stars");
      if (hfr !== null) parts.push(`HFR ${formatDecimal(hfr, locale, 2)}`);
      if (stars !== null) parts.push(t.session.stars(stars));
      return parts.join(" · ");
    }
    case "action":
      switch (event.message) {
        case "autofocus": {
          const position = number("position");
          const hfr = number("hfr");
          return position !== null && hfr !== null
            ? e.focused(formatPlain(position, locale), formatDecimal(hfr, locale, 2))
            : n.autofocus;
        }
        case "cool": {
          const temperature = number("temperature");
          return temperature !== null ? e.cooled(formatTemperature(temperature, locale)) : n.cool("—");
        }
        case "wait":
          return e.waited(t.session.step.wait, formatDuration(number("waited") ?? 0));
        case "filter":
          return n.filter(String(data.filter ?? ""));
        case "guide":
          return data.on === false ? n.guideOff : n.guideOn;
        case "center": {
          const attempts = number("attempts");
          return attempts !== null ? e.centered(attempts, formatDecimal(number("error") ?? 0, locale, 1)) : n.center;
        }
        case "recenter": {
          const drift = number("drift");
          if (typeof data.error === "string") return e.checkFailed(data.error);
          if (drift === null) return n.recenter;
          return data.centered ? e.recentered(formatDecimal(drift, locale, 1)) : e.checked(formatDecimal(drift, locale, 1));
        }
        case "flip":
          return e.flipped(typeof data.pier_side === "string" ? data.pier_side : "?");
        case "dither":
          return typeof data.skipped === "string" ? e.ditherSkipped : e.dithered(formatDecimal(number("pixels") ?? 0, locale, 1));
        case "aim":
          return e.aimed(typeof data.name === "string" ? data.name : "?", typeof data.ra === "number");
        case "prompt":
          return e.ready(t.sequence.prompt[promptKind(data.frame_type)].title);
        case "flats":
          return e.flats(number("frames") ?? 0, typeof data.master === "string");
        case "kept":
          if (typeof data.master === "string") return e.master(t.sequence.kinds[promptKindOf(data.master)], number("frames") ?? 0);
          return Array.isArray(data.stacks) ? e.stacks(data.stacks.length) : event.message;
        case "unpark":
          return n.unpark;
        case "park":
          return n.park;
        case "slew":
          return n.slew;
        case "warm":
          return n.warm;
        default:
          return event.message;
      }
  }
}

function promptKindOf(kind: unknown): "dark" | "bias" | "flat" {
  return kind === "bias" ? "bias" : kind === "flat" ? "flat" : "dark";
}

// What the run is doing between frames: the step at `run.current`.
export function describeStep(run: SequenceRun, t: Messages, locale: string, outputs: PowerOutput[]): string {
  const step = run.step as Node | null | undefined;
  if (!step) return t.session.step.between;
  if (step.kind === "expose") return t.session.step.expose;
  return describeNode(step, t, locale, outputs);
}
