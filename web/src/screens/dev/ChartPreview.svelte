<script lang="ts">
  // A place to try the framing chart (#/dev/chart) until the Plan screen (3.6)
  // hosts it: pick a target, a camera and a rotation.
  import Icon from "../../components/Icon.svelte";
  import ScreenHeader from "../../components/ScreenHeader.svelte";
  import SegmentedControl from "../../components/SegmentedControl.svelte";
  import SkyChart from "../../components/SkyChart.svelte";
  import TextField from "../../components/TextField.svelte";
  import { searchTargets } from "../../lib/api";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href } from "../../lib/router.svelte";
  import type { CameraRoleName, CatalogMatch, CatalogObject } from "../../lib/types";

  const t = $derived(i18n.t);

  // NGC 292, the Small Magellanic Cloud: the phase's first exit target.
  let target: CatalogObject | null = $state(null);
  let query = $state("NGC 292");
  let matches: CatalogMatch[] = $state([]);
  let searched = $state(false);
  let role: CameraRoleName = $state("main_camera");
  let rotation = $state(0);

  const field = $derived(live.app.cameras?.[role]?.field ?? null);
  const roles = $derived(
    (["main_camera", "guide_camera"] as const)
      .filter((r) => live.app.cameras?.[r])
      .map((r) => ({ value: r, label: t.roles[r] })),
  );

  let seq = 0;
  $effect(() => {
    const text = query.trim();
    const id = ++seq;
    if (!text) {
      matches = [];
      return;
    }
    const timer = setTimeout(async () => {
      try {
        const found = await searchTargets(text, 6);
        if (id !== seq) return;
        matches = found;
        searched = true;
        // The first time, open on the first match.
        if (!target && found[0]) target = found[0].object;
      } catch {
        if (id === seq) matches = [];
      }
    }, 200);
    return () => clearTimeout(timer);
  });

  function name(object: CatalogObject): string {
    const names = i18n.locale === "es" && object.names_es.length ? object.names_es : object.names;
    return names[0] ? `${object.label} · ${names[0]}` : object.label;
  }
</script>

<div class="preview">
  <a class="back" href={href({ screen: "dev" })}><Icon name="chevronLeft" />Dev</a>
  <ScreenHeader title={t.chartPreview.title} />
  <p class="intro">{t.chartPreview.intro}</p>

  <TextField label={t.chartPreview.target} hint={t.chartPreview.targetHint} bind:value={query} />
  <div class="matches">
    {#each matches as match (match.object.id)}
      <button
        type="button"
        class="match"
        class:selected={target?.id === match.object.id}
        onclick={() => (target = match.object)}>{name(match.object)}</button>
    {:else}
      {#if searched && query.trim()}<p class="muted">{t.chartPreview.noMatch}</p>{/if}
    {/each}
  </div>

  {#if roles.length > 1}
    <SegmentedControl label={t.chartPreview.camera} options={roles} value={role} onchange={(r) => (role = r)} />
  {/if}
  {#if !field}<p class="muted">{t.chartPreview.noField}</p>{/if}

  <label class="rotation">
    <span class="label">{t.chartPreview.rotation} <span class="mono">{rotation}°</span></span>
    <input type="range" min="0" max="359" step="1" bind:value={rotation} />
    <span class="hint">{t.chartPreview.rotationHint}</span>
  </label>

  {#if target}
    <div class="frame">
      {#key target.id}
        <SkyChart target={target} {field} {rotation} highlight={target.id} span={field ? Math.max(1, field.width * 2.5) : 4} />
      {/key}
    </div>
  {/if}
</div>

<style>
  .preview {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
    padding-bottom: var(--space-6);
  }
  .back {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    color: var(--accent);
    text-decoration: none;
  }
  .intro,
  .muted,
  .hint {
    color: var(--muted);
    margin: 0;
  }
  .hint {
    font-size: 12px;
    line-height: 16px;
  }
  .matches {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .match {
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    border-radius: var(--radius-full);
    background: var(--surface);
    color: var(--text);
    font: inherit;
  }
  .match.selected {
    border-color: var(--accent);
    color: var(--accent);
  }
  .rotation {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  .rotation input {
    min-height: var(--touch);
    accent-color: var(--accent);
  }
  .mono {
    font-family: var(--font-mono);
  }
  .frame {
    height: min(70dvh, 640px);
    min-height: 360px;
    margin: 0 calc(-1 * var(--margin));
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
  }
</style>
