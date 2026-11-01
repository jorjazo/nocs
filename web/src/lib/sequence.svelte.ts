// The sequence builder's draft (phase 5.13): the template being edited for
// tonight's target, kept while the page is open so that going to another tab
// and back loses nothing; and the words for a template and its steps.

import { listSequences } from "./api";
import { formatPlain, formatTemperature, formatTime } from "./format";
import type { Messages } from "./i18n";
import { newTemplate, sequenceId } from "./sequence";
import type { Container, Node, PlannedTarget, PowerOutput, Template } from "./types";

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
  async open(target: PlannedTarget, filter: string | null, guide: boolean): Promise<void> {
    this.loading = true;
    const fresh = newTemplate(target, filter, guide);
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
  for (const trigger of container.triggers ?? []) {
    const s = t.sequence;
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
