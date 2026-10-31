<script lang="ts">
  // The power box (ADR 0017): input, outputs with what they feed, the
  // adjustable output's voltage, dew heaters and auto-dew. Switching an output
  // off or changing a voltage takes a second tap; the server refuses it while
  // what the output feeds is busy, and a third choice forces it.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Chip from "../../components/Chip.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import Toggle from "../../components/Toggle.svelte";
  import { ApiError, setAutoDew, setOutput } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatDecimal, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import type { OutputRequest, PowerOutput } from "../../lib/types";

  let { onclose }: { onclose: () => void } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  const power = $derived(live.app.power ?? null);
  const switched = $derived(power?.outputs.filter((o) => o.kind !== "dew") ?? []);
  const heaters = $derived(power?.outputs.filter((o) => o.kind === "dew") ?? []);
  const disabled = $derived(!auth.owner);

  let busy = $state<string | null>(null);
  let errors = $state<Record<string, string>>({});
  // Outputs the server refused to cut because what they feed is busy.
  let refused = $state<Record<string, OutputRequest>>({});
  // A voltage picked for the adjustable output, waiting for its second tap.
  let pendingVoltage = $state<Record<string, string>>({});
  let duties = $state<Record<string, number | null>>({});

  async function change(output: PowerOutput, request: OutputRequest): Promise<void> {
    busy = output.id;
    errors = { ...errors, [output.id]: "" };
    try {
      await setOutput(output.id, request);
      delete refused[output.id];
      delete pendingVoltage[output.id];
    } catch (e) {
      errors = { ...errors, [output.id]: errorText(e, t) };
      if (e instanceof ApiError && e.status === 409 && !request.force) {
        refused = { ...refused, [output.id]: { ...request, force: true } };
      }
    } finally {
      busy = null;
    }
  }

  async function autoDew(on: boolean): Promise<void> {
    busy = "auto-dew";
    errors = { ...errors, "auto-dew": "" };
    try {
      await setAutoDew(on);
    } catch (e) {
      errors = { ...errors, "auto-dew": errorText(e, t) };
    } finally {
      busy = null;
    }
  }

  function volts(value: number): string {
    return `${formatPlain(value, locale)} V`;
  }

  function amps(value: number | null): string {
    return value === null ? "" : t.power.amps(formatDecimal(value, locale, 2));
  }

  function feeds(output: PowerOutput): string {
    if (output.feeds.length === 0) return t.power.feedsUnknown;
    return t.power.feeds(output.feeds.map((role) => t.roles[role].toLowerCase()).join(", "));
  }

  function voltageOptions(output: PowerOutput): { value: string; label: string }[] {
    return [{ value: "off", label: t.power.off }, ...output.voltages.map((v) => ({ value: String(v), label: volts(v) }))];
  }

  // The box went away (disconnected): nothing left to control.
  $effect(() => {
    if (!power) onclose();
  });
</script>

<Sheet title={power?.device ?? t.power.title} {onclose}>
  {#if power}
    {#if power.input}
      <div class="readouts">
        <div>
          <span class="label muted">{t.power.input}</span>
          <span class="readout">{power.input.voltage === null ? "—" : `${formatDecimal(power.input.voltage, locale, 1)} V`}</span>
        </div>
        <div>
          <span class="label muted">{t.power.current}</span>
          <span class="readout">{power.input.current === null ? "—" : `${formatDecimal(power.input.current, locale, 2)} A`}</span>
        </div>
        <div>
          <span class="label muted">{t.power.power}</span>
          <span class="readout">{power.input.power === null ? "—" : `${formatDecimal(power.input.power, locale, 0)} W`}</span>
        </div>
      </div>
    {/if}

    {#if switched.length > 0}
      <section class="group" aria-label={t.power.outputs}>
        <h3 class="label muted">{t.power.outputs}</h3>
        {#each switched as output (output.id)}
          <div class="output">
            <div class="line">
              <span class="name">{output.label}</span>
              <Chip tone={output.on ? "ok" : "neutral"}>
                {output.on ? (output.voltage !== null ? volts(output.voltage) : t.power.on) : t.power.off}
              </Chip>
            </div>
            <p class="caption muted">{[feeds(output), output.on ? amps(output.current) : ""].filter(Boolean).join(" · ")}</p>

            {#if output.kind === "variable"}
              {@const picked = pendingVoltage[output.id]}
              {@const current = output.voltage === null ? "off" : String(output.voltage)}
              <SegmentedControl
                label={t.power.voltage}
                options={voltageOptions(output)}
                value={picked ?? current}
                onchange={(value) => {
                  if (disabled) return;
                  pendingVoltage = { ...pendingVoltage, [output.id]: value };
                  delete refused[output.id];
                }} />
              {#if picked !== undefined && picked !== current}
                {@const label = picked === "off" ? t.power.off.toLowerCase() : volts(Number(picked))}
                {#if picked !== "off"}<p class="caption warning">{t.power.voltageHint}</p>{/if}
                <div class="buttons">
                  <ConfirmButton
                    label={t.power.setVoltage(label)}
                    confirmLabel={t.power.confirmVoltage(label)}
                    busy={busy === output.id}
                    onconfirm={() =>
                      void change(output, picked === "off" ? { on: false } : { voltage: Number(picked) })} />
                  <Button
                    variant="text"
                    onclick={() => {
                      delete pendingVoltage[output.id];
                      delete refused[output.id];
                    }}>{t.power.cancel}</Button>
                </div>
              {/if}
            {:else if !disabled}
              <div class="buttons">
                {#if output.on}
                  <ConfirmButton
                    label={t.power.switchOff}
                    confirmLabel={t.power.confirmOff}
                    busy={busy === output.id}
                    onconfirm={() => void change(output, { on: false })} />
                {:else}
                  <Button busy={busy === output.id} onclick={() => void change(output, { on: true })}>
                    {t.power.switchOn}
                  </Button>
                {/if}
              </div>
            {/if}

            {#if errors[output.id]}
              <Banner icon="alert" tone="error">{errors[output.id]}</Banner>
            {/if}
            {#if refused[output.id]}
              <ConfirmButton
                label={t.power.forceOff}
                confirmLabel={t.power.confirmForce}
                busy={busy === output.id}
                onconfirm={() => void change(output, refused[output.id] ?? { on: false, force: true })} />
            {/if}
          </div>
        {/each}
      </section>
    {/if}

    {#if heaters.length > 0 || power.auto_dew !== null}
      <section class="group" aria-label={t.power.dew}>
        <h3 class="label muted">{t.power.dew}</h3>
        {#if power.auto_dew !== null}
          <Toggle
            label={t.power.autoDew}
            hint={power.auto_dew_aggression !== null
              ? t.power.autoDewHint(`${formatPlain(power.auto_dew_aggression, locale)} %`)
              : undefined}
            checked={power.auto_dew}
            disabled={disabled || busy === "auto-dew"}
            onchange={(on) => void autoDew(on)} />
          {#if errors["auto-dew"]}<Banner icon="alert" tone="error">{errors["auto-dew"]}</Banner>{/if}
          {#if power.auto_dew && heaters.length > 0}<p class="caption muted">{t.power.autoDewOn}</p>{/if}
        {/if}
        {#each heaters as heater (heater.id)}
          {@const manual = !disabled && !power.auto_dew}
          <div class="output">
            <div class="line">
              <span class="name">{heater.label}</span>
              <Chip tone={heater.on && (heater.duty ?? 0) > 0 ? "ok" : "neutral"}>
                {heater.on ? `${formatPlain(heater.duty ?? 0, locale)} %` : t.power.off}
              </Chip>
            </div>
            {#if heater.on && heater.current !== null}<p class="caption muted">{amps(heater.current)}</p>{/if}
            <Toggle
              label={t.power.on}
              checked={heater.on}
              disabled={!manual || busy === heater.id}
              onchange={(on) => void change(heater, { on })} />
            <div class="duty">
              <Stepper
                label={t.power.duty}
                bind:value={() => duties[heater.id] ?? heater.duty ?? 0, (value) => (duties[heater.id] = value)}
                min={0}
                max={100}
                step={10}
                unit="%"
                disabled={!manual} />
              <Button
                busy={busy === heater.id}
                disabled={!manual || duties[heater.id] == null || duties[heater.id] === heater.duty}
                onclick={() => void change(heater, { duty: duties[heater.id] ?? 0 })}>
                {t.power.setDuty}
              </Button>
            </div>
            {#if errors[heater.id]}<Banner icon="alert" tone="error">{errors[heater.id]}</Banner>{/if}
          </div>
        {/each}
      </section>
    {/if}
  {/if}
</Sheet>

<style>
  .readouts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: var(--space-3);
  }
  .readouts > div {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-tile);
    background: var(--raised);
    min-width: 0;
  }
  .readout {
    font-family: var(--font-mono);
    font-size: 20px;
    line-height: 26px;
    font-weight: 500;
  }
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .group h3 {
    margin: 0;
  }
  .output {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding-bottom: var(--space-3);
    border-bottom: 1px solid var(--line);
  }
  .line {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }
  .name {
    font-size: 17px;
    line-height: 24px;
    font-weight: 600;
    min-width: 0;
    overflow-wrap: anywhere;
  }
  .caption {
    margin: 0;
  }
  .warning {
    color: var(--warning);
  }
  .buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .duty {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: center;
    gap: var(--space-3);
  }
</style>
