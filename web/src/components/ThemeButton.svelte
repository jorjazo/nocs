<script lang="ts">
  import { i18n } from "../lib/i18n";
  import { prefs } from "../lib/prefs.svelte";
  import Icon from "./Icon.svelte";
</script>

<button
  type="button"
  class="theme"
  class:on={prefs.theme === "night"}
  aria-label={i18n.t.theme.toggle}
  aria-pressed={prefs.theme === "night"}
  onclick={() => prefs.toggleTheme()}>
  <Icon name="night" />
</button>

<style>
  .theme {
    flex: none;
    display: grid;
    place-items: center;
    width: 48px;
    height: 48px;
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--text);
    cursor: pointer;
  }
  /* Pressed shows as a filled tile, not only a color change. */
  .on {
    background: var(--raised);
    border-color: var(--accent);
  }
</style>
