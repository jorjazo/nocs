<script lang="ts">
  // Configure the sequence (#/sequence/edit): which saved sequence, its name, and its
  // groups in order: their kind, filter, exposure and frames. Changes are saved a
  // moment after they are made. The calibration its lights still lack can be added as
  // groups; when the kind of frames changes between groups the run asks the user to
  // ready the rig, and the page says where.
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import EmptyState from "../../components/EmptyState.svelte";
  import Icon from "../../components/Icon.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import Stepper from "../../components/Stepper.svelte";
  import TextField from "../../components/TextField.svelte";
  import { estimateTemplate, expandTemplate, missingCalibration } from "../../lib/api";
  import { auth } from "../../lib/auth.svelte";
  import { errorText } from "../../lib/errors";
  import { formatBytes, formatDuration, formatPlain } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { router } from "../../lib/router.svelte";
  import { groupSeconds, isActive, newGroup, prompts } from "../../lib/sequence";
  import { groupFrames, groupName, groupSettings, sequences } from "../../lib/sequence.svelte";
  import type { Sequence, SequenceEstimate } from "../../lib/types";
  import GroupSheet from "./GroupSheet.svelte";
  import SequenceSteps from "./SequenceSteps.svelte";

  const t = $derived(i18n.t);
  const s = $derived(t.sequence);
  const locale = $derived(i18n.locale);
  const run = $derived(live.app.sequence?.run ?? null);
  const going = $derived(isActive(run) ? run : null);
  const camera = $derived(live.app.cameras?.main_camera ?? null);
  const wheel = $derived(live.app.filter_wheel ?? null);
  const filters = $derived((wheel?.names ?? []).filter((name) => name));
  const outputs = $derived(live.app.power?.outputs ?? []);

  $effect(() => {
    if (auth.owner && !sequences.loaded) void sequences.load(going?.sequence ?? null);
  });
  const draft = $derived(sequences.draft);
  // The running sequence cannot change until it ends.
  const locked = $derived(going?.sequence === sequences.id);
  $effect(() => {
    if (!draft) return;
    void JSON.stringify(draft);
    sequences.changed();
  });

  const ids = $derived(Object.keys(sequences.all).filter((id) => sequences.all[id]?.template));
  let editing = $state<number | null>(null);
  let busy = $state(false);
  let error = $state("");
  let note = $state("");
  let advanced = $state(false);
  let estimate = $state<SequenceEstimate | null>(null);
  let steps = $state<Sequence | null>(null);

  let asked = 0;
  $effect(() => {
    if (!draft) return;
    const body = $state.snapshot(draft);
    const withSteps = advanced;
    const id = ++asked;
    const timer = setTimeout(() => {
      estimateTemplate(body)
        .then((found) => {
          if (id === asked) estimate = found;
        })
        .catch(() => {});
      if (withSteps) {
        expandTemplate(body)
          .then((found) => {
            if (id === asked) steps = found;
          })
          .catch(() => {});
      }
    }, 300);
    return () => clearTimeout(timer);
  });

  const asks = $derived(draft ? prompts(draft.groups) : []);

  async function run_(call: () => Promise<void>): Promise<void> {
    busy = true;
    error = "";
    note = "";
    try {
      await call();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }

  function create(): void {
    void run_(() =>
      sequences.create(s.newName, wheel?.filter ?? filters[0] ?? null, !!live.app.equipment?.devices.guide_camera, live.app.solver?.available === true, {
        gain: camera?.gain ?? null,
        offset: camera?.offset ?? null,
      }),
    );
  }

  function addGroup(): void {
    if (!draft) return;
    draft.groups.push(newGroup(draft.groups, filters, { gain: camera?.gain ?? null, offset: camera?.offset ?? null }));
    editing = draft.groups.length - 1;
  }

  function move(index: number, by: number): void {
    if (!draft) return;
    const to = index + by;
    if (to < 0 || to >= draft.groups.length) return;
    const [group] = draft.groups.splice(index, 1);
    if (group) draft.groups.splice(to, 0, group);
  }

  function addMissing(): void {
    const id = sequences.id;
    if (!draft || !id) return;
    void run_(async () => {
      await sequences.save();
      const groups = await missingCalibration(id);
      if (!groups.length) {
        note = s.missingNone;
        return;
      }
      draft.groups.push(...groups);
      note = s.missingAdded(groups.length);
    });
  }

  function leave(): void {
    sequences.flush();
    router.go({ screen: "sequence" });
  }
</script>

<ScreenHeader title={s.configureTitle}>
  {#snippet trailing()}
    <Button variant="text" onclick={leave}>{s.row.done}</Button>
  {/snippet}
</ScreenHeader>

<div class="screen">
  {#if !auth.owner}
    <EmptyState icon="sequence" title={s.ownerOnly} body="" />
  {:else}
    {#if ids.length > 1 || !draft}
      <section aria-labelledby="saved">
        <h2 id="saved">{s.choose}</h2>
        <ul class="saved">
          {#each ids as id (id)}
            <li>
              <button type="button" class="pick" aria-pressed={id === sequences.id} onclick={() => sequences.show(id)}>
                <Icon name={id === sequences.id ? "check" : "sequence"} size={20} />
                <span>{sequences.all[id]?.name ?? id}</span>
              </button>
            </li>
          {/each}
        </ul>
      </section>
    {/if}
    <Button variant={draft ? "text" : "primary"} busy={busy && !draft} disabled={busy} onclick={create}>{s.create}</Button>

    {#if !draft}
      {#if sequences.loaded && !ids.length}<EmptyState icon="sequence" title={s.none} body={s.noneBody} />{/if}
    {:else}
      {#if locked}<Banner icon="sequence">{s.readOnly}</Banner>{/if}
      <fieldset disabled={locked}>
        <TextField label={s.name} bind:value={draft.name} required maxlength={80} />

        <section aria-labelledby="groups">
          <div class="heading">
            <h2 id="groups">{s.groups}</h2>
            <Button variant="text" onclick={addGroup}>{s.addGroup}</Button>
          </div>
          <ol class="groups">
            {#each draft.groups as group, i (i)}
              <li>
                <button type="button" class="group-main" onclick={() => (editing = i)}>
                  <span class="badge" class:calibration={(group.frame_type ?? "light") !== "light"}>{groupName(group, t)}</span>
                  <span class="text">
                    <span class="mono">{groupFrames(group, t, locale)}</span>
                    <span class="muted small">{formatDuration(groupSeconds(group))} · {groupSettings(group, draft, t, locale)}</span>
                  </span>
                </button>
                <button type="button" class="nudge" aria-label={s.moveUp(groupName(group, t))} disabled={i === 0} onclick={() => move(i, -1)}>
                  <Icon name="up" />
                </button>
                <button
                  type="button"
                  class="nudge"
                  aria-label={s.moveDown(groupName(group, t))}
                  disabled={i === draft.groups.length - 1}
                  onclick={() => move(i, 1)}>
                  <Icon name="down" />
                </button>
              </li>
            {/each}
          </ol>
          <div class="missing">
            <Button disabled={busy} {busy} onclick={addMissing}>{s.addMissing}</Button>
            <p class="muted small">{note || s.addMissingHint}</p>
          </div>
          {#if asks.length}
            <p class="muted small">{s.asks} {asks.map((kind) => s.prompt[kind].title.toLowerCase()).join(" · ")}.</p>
          {/if}
        </section>
      </fieldset>

      {#if estimate}
        <section class="estimates">
          <div class="card estimate">
            <span class="muted small">{s.imagingTime}</span>
            <span class="mono">{formatDuration(estimate.duration)}</span>
          </div>
          <div class="card estimate">
            <span class="muted small">{s.framesTotal(estimate.frames)}</span>
            <span class="mono">{estimate.bytes !== null ? formatBytes(estimate.bytes, locale) : "—"}</span>
          </div>
        </section>
      {/if}
      {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}
      {#if sequences.error}<Banner icon="alert" tone="error">{sequences.error}</Banner>{/if}
      <p class="caption muted" aria-live="polite">{sequences.saving ? s.savingDraft : sequences.dirty ? "" : s.savedDraft}</p>

      <button type="button" class="disclosure" aria-expanded={advanced} onclick={() => (advanced = !advanced)}>
        <Icon name={advanced ? "chevronDown" : "chevronRight"} size={20} />
        {s.advanced}
      </button>
      {#if advanced}
        <section class="advanced">
          <fieldset disabled={locked}>
            {#if draft.order !== "in_turn"}
              <Stepper label={s.batch} bind:value={() => draft.batch ?? 5, (v) => v !== null && (draft.batch = v)} min={1} max={1000} />
            {/if}
            {#if draft.flip !== false}
              <Stepper
                label={s.flipAfter}
                bind:value={() => draft.flip_after ?? 5, (v) => v !== null && (draft.flip_after = v)}
                min={0}
                max={60}
                unit="min" />
            {/if}
          </fieldset>
          <h2>{s.steps}</h2>
          <p class="muted small">{s.stepsHint}</p>
          {#if steps}<SequenceSteps sequence={steps} {outputs} />{/if}
          {#if !locked && sequences.id}
            <ConfirmButton
              label={s.remove}
              confirmLabel={s.removeConfirm}
              onconfirm={() => {
                const id = sequences.id;
                if (id) void run_(() => sequences.remove(id));
              }} />
          {/if}
        </section>
      {/if}
    {/if}
  {/if}
</div>

{#if draft && editing !== null && !locked}
  {@const group = draft.groups[editing]}
  {#if group}
    <GroupSheet
      {group}
      {filters}
      perGroupCooling={draft.cooling === "group"}
      canRemove={draft.groups.length > 1}
      onremove={() => {
        if (editing !== null) draft.groups.splice(editing, 1);
        editing = null;
      }}
      onclose={() => (editing = null)} />
  {/if}
{/if}

<style>
  .screen {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin-top: var(--space-4);
    padding-bottom: var(--space-6);
  }
  fieldset {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
  }
  h2 {
    margin: 0;
    font-size: 15px;
    line-height: 22px;
    font-weight: 600;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
  p {
    margin: 0;
  }
  .mono {
    font-family: var(--font-mono);
  }
  .heading {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .saved,
  .groups {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .pick {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    min-height: 48px;
    padding: 0;
    border: 0;
    border-bottom: 1px solid var(--line);
    background: transparent;
    color: var(--text);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .pick[aria-pressed="true"] {
    color: var(--accent);
    font-weight: 600;
  }
  .groups li {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: 56px;
    border-bottom: 1px solid var(--line);
  }
  .group-main {
    flex: 1;
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-width: 0;
    min-height: 56px;
    padding: var(--space-1) 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
    text-align: left;
  }
  .badge {
    flex: none;
    min-width: 56px;
    height: 28px;
    padding: 0 var(--space-2);
    display: grid;
    place-items: center;
    background: var(--raised);
    font-size: 13px;
    font-weight: 600;
  }
  .badge.calibration {
    background: transparent;
    border: 1px solid var(--line);
  }
  .nudge {
    flex: none;
    width: var(--touch);
    height: var(--touch);
    display: grid;
    place-items: center;
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  .nudge:disabled {
    color: var(--muted);
    cursor: default;
  }
  .missing {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-1);
    margin-top: var(--space-3);
  }
  .estimates {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: var(--space-2);
  }
  .estimate {
    display: flex;
    flex-direction: column;
    padding: var(--space-2) var(--space-3);
  }
  .disclosure {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--touch);
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font: inherit;
    cursor: pointer;
  }
  .advanced {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
