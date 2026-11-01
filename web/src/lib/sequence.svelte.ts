// The sequence builder's draft (phase 5.13): the template being edited for
// tonight's target, kept while the page is open so that going to another tab
// and back loses nothing; and the words for a template and its steps.

import { listSequences } from "./api";
import { formatDecimal, formatDuration, formatPlain, formatTemperature, formatTime } from "./format";
import type { Messages } from "./i18n";
import type { AutofocusTrigger, DitherTrigger, FlipTrigger, RecenterTrigger } from "./generated/api";
import { newTemplate, sequenceId } from "./sequence";
import type { Container, Node, PlannedTarget, PowerOutput, SequenceEvent, SequenceRun, Template } from "./types";

export { isActive, nextFilter, rowSeconds, sequenceId } from "./sequence";

class Builder {
  draft: Template | null = $state(null);
  // What was last saved or loaded, to tell unsaved changes.
  private saved = $state("");
  loading = $state(false);

  get id(): string | null {
    return this.draft ? sequenceId(this.draft.target.name) : null;
  }

  get dirty(): boolean {
    return this.draft !== null && JSON.stringify(this.draft) !== this.saved;
  }

  // Edit the target's saved sequence, or a new one.
  async open(target: PlannedTarget, filter: string | null, guide: boolean, solver: boolean): Promise<void> {
    this.loading = true;
    const fresh = newTemplate(target, filter, guide, solver);
    try {
      const stored = (await listSequences())[sequenceId(target.name)]?.template;
      this.draft = stored ? { ...fresh, ...stored } : fresh;
      this.saved = stored ? JSON.stringify(this.draft) : "";
    } catch {
      this.draft = fresh;
      this.saved = "";
    } finally {
      this.loading = false;
    }
  }

  markSaved(): void {
    this.saved = JSON.stringify(this.draft);
  }
}

export const builder = new Builder();

// -- Words for a template and for the steps it makes ---------------------------

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
      return node.name === "imaging" ? n.imaging : node.name || node.target?.name || "";
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
    case "ended": {
      const outcome = event.message as keyof typeof t.session.states;
      const ended = e.ended(t.session.states[outcome] ?? event.message);
      return typeof data.error === "string" ? `${ended} · ${data.error}` : ended;
    }
    case "failed":
      return e.failed(event.message);
    case "recovery":
      return data.guard ? e.guard : e.recovery(event.message);
    case "skipped":
      return e.skipped(event.message);
    case "trigger": {
      const waiting = /^flip: waiting ([\d.]+) min/.exec(event.message);
      if (waiting) return e.flipWaiting(formatDecimal(Number(waiting[1]), locale, 1));
      if (event.message.startsWith("flip:")) return e.flipDue;
      return e.trigger(event.message.replace(/^autofocus: /, ""));
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

// What the run is doing between frames: the step at `run.current`.
export function describeStep(run: SequenceRun, t: Messages, locale: string, outputs: PowerOutput[]): string {
  const step = run.step as Node | null | undefined;
  if (!step) return t.session.step.between;
  if (step.kind === "expose") return t.session.step.expose;
  return describeNode(step, t, locale, outputs);
}
