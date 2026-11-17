<script lang="ts">
  // The target name for lights, which names their folder (Light/<target>/) and
  // the OBJECT header (ADR 0013). Suggestions: the targets of recent nights while
  // the field is empty, then objects of the bundled catalog as it is typed.
  import { untrack } from "svelte";
  import Banner from "../../components/Banner.svelte";
  import Button from "../../components/Button.svelte";
  import Sheet from "../../components/Sheet.svelte";
  import TextField from "../../components/TextField.svelte";
  import { getNights, searchTargets, setTarget } from "../../lib/api";
  import { errorText } from "../../lib/errors";
  import { i18n } from "../../lib/i18n";

  let { current, onclose }: { current: string | null; onclose: () => void } = $props();

  const t = $derived(i18n.t);
  let name = $state(untrack(() => current) ?? "");
  let busy = $state(false);
  let error = $state("");

  type Suggestion = { name: string; detail: string | null };
  let recent = $state<Suggestion[]>([]);
  let matches = $state<Suggestion[]>([]);
  const query = $derived(name.trim());
  const suggestions = $derived(query ? matches : recent);

  $effect(() => {
    getNights()
      .then((nights) => {
        const seen = new Set<string>();
        for (const night of nights.slice(0, 5)) {
          for (const group of night.groups) {
            if (group.target) seen.add(group.target);
          }
        }
        recent = [...seen].slice(0, 6).map((target) => ({ name: target, detail: null }));
      })
      .catch(() => {
        // No catalog (yet): no suggestions, nothing else depends on them.
      });
  });

  // The catalog is searched a moment after typing stops; an older answer never
  // replaces a newer one.
  let asked = 0;
  $effect(() => {
    const text = query;
    if (!text || text === current) {
      matches = [];
      return;
    }
    const id = ++asked;
    const timer = setTimeout(() => {
      searchTargets(text, 6)
        .then((found) => {
          if (id !== asked) return;
          matches = found.map(({ object }) => {
            const common = (i18n.locale === "es" ? object.names_es[0] : undefined) ?? object.names[0];
            return { name: object.label, detail: common ?? (object.label === object.id ? null : object.id) };
          });
        })
        .catch(() => {
          if (id === asked) matches = [];
        });
    }, 250);
    return () => clearTimeout(timer);
  });

  async function save(target: string | null): Promise<void> {
    busy = true;
    error = "";
    try {
      await setTarget(target);
      onclose();
    } catch (e) {
      error = errorText(e, t);
    } finally {
      busy = false;
    }
  }
</script>

<Sheet title={t.live.target} {onclose}>
  <form
    onsubmit={(event) => {
      event.preventDefault();
      void save(query || null);
    }}>
    <TextField label={t.live.targetName} hint={t.live.targetHint} bind:value={name} maxlength={80} autocomplete="off" />
  </form>
  {#if suggestions.length > 0}
    <div class="suggestions" role="group" aria-label={query ? t.live.targetCatalog : t.live.targetRecent}>
      <span class="label muted">{query ? t.live.targetCatalog : t.live.targetRecent}</span>
      <ul>
        {#each suggestions as suggestion (suggestion.name)}
          <li>
            <button type="button" onclick={() => (name = suggestion.name)}>
              <span class="name">{suggestion.name}</span>
              {#if suggestion.detail}<span class="caption muted">{suggestion.detail}</span>{/if}
            </button>
          </li>
        {/each}
      </ul>
    </div>
  {/if}
  {#if error}<Banner icon="alert" tone="error">{error}</Banner>{/if}

  {#snippet actions()}
    {#if current}
      <Button variant="text" disabled={busy} onclick={() => void save(null)}>{t.live.targetClear}</Button>
    {/if}
    <Button variant="primary" {busy} disabled={query === (current ?? "")} onclick={() => void save(query || null)}>
      {t.live.targetSave}
    </Button>
  {/snippet}
</Sheet>

<style>
  .suggestions {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
  ul {
    display: flex;
    flex-direction: column;
    margin: 0;
    padding: 0;
    list-style: none;
    border: 1px solid var(--line);
    border-radius: var(--radius-tile);
  }
  li + li {
    border-top: 1px solid var(--line);
  }
  li button {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    width: 100%;
    min-height: var(--touch);
    padding: var(--space-2) var(--space-3);
    border: 0;
    background: transparent;
    color: var(--text);
    text-align: left;
    cursor: pointer;
  }
  .name {
    font-weight: 600;
  }
</style>
