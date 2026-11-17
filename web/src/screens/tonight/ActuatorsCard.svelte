<script lang="ts">
  // Tonight's "Actuators" card, read only: the dew heaters (power, current, fixed or
  // automatic), the 12 V outputs, the power box's input, and the camera's cooler
  // (the sensor against its target, the cooler's power, the ramp). Warns when the
  // input runs low and when the sensor stays off its target after its ramp had time.
  // Closed: the power drawn and the sensor's temperature. They are set in Rig.
  import Section from "../../components/Section.svelte";
  import { formatDecimal, formatTemperature } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { coolerOffTarget, inputAttention, type CoolerStart } from "../../lib/tonightcards";
  import type { PowerOutput } from "../../lib/types";

  let { now, open, ontoggle }: { now: number; open: boolean; ontoggle: (open: boolean) => void } = $props();

  const t = $derived(i18n.t);
  const a = $derived(t.tonight.actuators);
  const locale = $derived(i18n.locale);
  const power = $derived(live.app.power ?? null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const cooled = $derived(camera?.can_cool ? camera : null);
  const dew = $derived(power?.outputs.filter((o) => o.kind === "dew") ?? []);
  const outputs = $derived(power?.outputs.filter((o) => o.kind === "dc" || o.kind === "variable") ?? []);
  const input = $derived(power?.input ?? null);
  const inputLow = $derived(inputAttention(input?.voltage));

  // When the sensor should reach its target: from when this target was first seen
  // with the cooler on, at the ramp's pace.
  let coolerStart: CoolerStart | null = $state(null);
  $effect(() => {
    const target = cooled?.cooler ? cooled.target : null;
    const temperature = cooled?.temperature ?? null;
    if (target === null || target === undefined || temperature === null) {
      coolerStart = null;
    } else if (coolerStart?.target !== target) {
      coolerStart = { at: Date.now(), temperature, target };
    }
  });
  const offTarget = $derived(coolerOffTarget(coolerStart, cooled?.temperature ?? null, cooled?.ramp ?? null, now));

  const amps = (value: number | null) => (value === null ? null : t.power.amps(formatDecimal(value, locale, 2)));
  function detail(output: PowerOutput): string {
    const parts = [output.on ? t.power.on : t.power.off];
    if (output.kind === "dew" && output.duty !== null) parts.push(`${formatDecimal(output.duty, locale, 0)} %`);
    if (output.kind === "variable" && output.on && output.voltage !== null) parts.push(a.volts(formatDecimal(output.voltage, locale, 1)));
    const current = output.on ? amps(output.current) : null;
    if (current) parts.push(current);
    return parts.join(" · ");
  }

  const coolerText = $derived.by(() => {
    if (!cooled) return null;
    if (!cooled.cooler) return a.coolerOff;
    const parts = [a.sensor(cooled.temperature === null ? "—" : formatTemperature(cooled.temperature, locale))];
    if (cooled.target !== null) parts.push(a.target(formatTemperature(cooled.target, locale)));
    return parts.join(", ");
  });

  const summary = $derived.by(() => {
    const parts: string[] = [];
    if (input?.power !== null && input?.power !== undefined) parts.push(a.watts(formatDecimal(input.power, locale, 0)));
    else if (input?.voltage) parts.push(a.volts(formatDecimal(input.voltage, locale, 1)));
    if (cooled) {
      parts.push(
        cooled.cooler && cooled.temperature !== null ? a.sensor(formatTemperature(cooled.temperature, locale)) : a.coolerOff,
      );
    }
    return parts.length ? parts.join(" · ") : a.none;
  });
  const status = $derived.by(() => {
    if (inputLow === "problem") return { tone: "error" as const, text: a.emptyBattery };
    if (inputLow === "warning") return { tone: "warning" as const, text: a.lowVoltage };
    if (offTarget) return { tone: "warning" as const, text: a.offTarget };
    return null;
  });
</script>

<Section scope="tonight" id="actuators" title={a.title} {summary} {status} {open} {ontoggle}>
  {#if !power && !cooled}
    <p class="muted">{a.none}</p>
  {/if}
  {#if cooled}
    <div class="group">
      <h3 class="label">{a.cooler}</h3>
      <div class="row">
        <span>{coolerText}</span>
        {#if offTarget}<span class="warning">{a.offTarget}</span>{/if}
      </div>
      {#if cooled.cooler}
        <span class="muted small">
          {[
            cooled.cooler_power === null ? null : a.coolerPower(`${formatDecimal(cooled.cooler_power, locale, 0)} %`),
            cooled.ramp ? a.ramp(formatDecimal(cooled.ramp, locale, 1)) : a.noRamp,
          ]
            .filter((part) => part !== null)
            .join(" · ")}
        </span>
      {/if}
    </div>
  {/if}
  {#if dew.length}
    <div class="group">
      <h3 class="label">
        {a.dew}{#if power?.auto_dew !== null && power?.auto_dew !== undefined}
          · {power.auto_dew ? a.auto : a.fixed}{/if}
      </h3>
      {#each dew as output (output.id)}
        <div class="row"><span>{output.label}</span><span class="muted">{detail(output)}</span></div>
      {/each}
    </div>
  {/if}
  {#if outputs.length}
    <div class="group">
      <h3 class="label">{a.outputs}</h3>
      {#each outputs as output (output.id)}
        <div class="row"><span>{output.label}</span><span class="muted">{detail(output)}</span></div>
      {/each}
    </div>
  {/if}
  {#if input}
    <div class="group">
      <h3 class="label">{a.input}</h3>
      <div class="row">
        <span class:warning={inputLow === "warning"} class:error={inputLow === "problem"}>
          {input.voltage === null ? "—" : a.volts(formatDecimal(input.voltage, locale, 1))}
        </span>
        <span class="muted">
          {[amps(input.current), input.power === null ? null : a.watts(formatDecimal(input.power, locale, 0))]
            .filter((part) => part !== null)
            .join(" · ")}
        </span>
      </div>
    </div>
  {/if}
</Section>

<style>
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  h3 {
    margin: 0;
    color: var(--muted);
  }
  .row {
    display: flex;
    justify-content: space-between;
    gap: var(--space-3);
    flex-wrap: wrap;
  }
  .small {
    font-size: 13px;
  }
  .warning {
    color: var(--warning);
  }
  .error {
    color: var(--error);
  }
  p {
    margin: 0;
  }
</style>
