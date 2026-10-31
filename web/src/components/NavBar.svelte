<script lang="ts">
  // Bottom tab bar on phones, left navigation rail from 768 px (docs/ux.md §1).
  import { i18n } from "../lib/i18n";
  import { href, router, TABS, type Tab } from "../lib/router.svelte";
  import Icon from "./Icon.svelte";
  import ThemeButton from "./ThemeButton.svelte";

  // The INDI property screen and the profile editor hang off Rig.
  const current = $derived<Tab>(
    router.route.screen === "dev" || router.route.screen === "profile" ? "rig" : router.route.screen,
  );
</script>

<nav class="nav" aria-label={i18n.t.tabs.label}>
  <span class="logo"><Icon name="logo" size={40} /></span>
  <ul>
    {#each TABS as tab (tab)}
      <li>
        <a href={href({ screen: tab })} aria-current={tab === current ? "page" : undefined}>
          <Icon name={tab} />
          <span class="name">{i18n.t.tabs[tab]}</span>
        </a>
      </li>
    {/each}
  </ul>
  <span class="theme"><ThemeButton /></span>
</nav>

<style>
  .nav {
    position: fixed;
    z-index: 10;
    left: 0;
    right: 0;
    bottom: 0;
    background: var(--surface);
    border-top: 1px solid var(--line);
    padding-bottom: env(safe-area-inset-bottom);
  }
  ul {
    display: flex;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    flex: 1 1 0;
    min-width: 0;
  }
  a {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    min-height: var(--tabbar-height);
    padding: var(--space-2) 2px;
    border-radius: var(--radius-button);
    color: var(--muted);
    text-decoration: none;
  }
  .name {
    font-size: 13px;
    line-height: 16px;
    font-weight: 500;
    text-align: center;
  }
  /* The current tab differs in weight and in a filled pill, not only in color. */
  a[aria-current="page"] {
    color: var(--accent);
  }
  a[aria-current="page"] .name {
    font-weight: 600;
  }
  .logo,
  .theme {
    display: none;
  }

  @media (max-width: 767px) {
    a[aria-current="page"] :global(.icon) {
      padding: 2px 14px;
      width: 52px;
      height: 28px;
      border-radius: var(--radius-full);
      background: var(--raised);
    }
  }

  @media (min-width: 768px) {
    .nav {
      top: 0;
      right: auto;
      width: var(--rail-width);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--space-6);
      padding: var(--space-6) var(--space-2) calc(var(--space-6) + env(safe-area-inset-bottom));
      border-top: 0;
      border-right: 1px solid var(--line);
    }
    .logo {
      display: block;
      color: var(--accent);
    }
    ul {
      flex-direction: column;
      gap: var(--space-2);
      width: 100%;
    }
    a {
      min-height: 72px;
    }
    a[aria-current="page"] {
      background: var(--raised);
    }
    .theme {
      display: block;
      margin-top: auto;
    }
  }
</style>
