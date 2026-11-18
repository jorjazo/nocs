<script lang="ts">
  // Bottom tab bar on phones, left navigation rail from 768 px (docs/ux.md §1).
  import { auth } from "../lib/auth.svelte";
  import { i18n } from "../lib/i18n";
  import { live } from "../lib/live.svelte";
  import { rigAttention } from "../lib/rigsections";
  import { href, router, TABS, type Tab } from "../lib/router.svelte";
  import { workingView } from "../lib/sequence";
  import Icon from "./Icon.svelte";
  import ThemeButton from "./ThemeButton.svelte";

  // The INDI property screen and the profile and site editors hang off Rig; the guided
  // flows (autofocus, guiding, polar alignment) belong to Tonight.
  const current = $derived.by<Tab>(() => {
    const screen = router.route.screen;
    if (screen === "dev" || screen === "profile" || screen === "site") return "rig";
    if (screen === "target") return "plan";
    if (screen === "sequence-edit") return "sequence";
    if (screen === "report" || screen === "flats") return "session";
    if (screen === "focus" || screen === "focus-calibration" || screen === "guiding" || screen === "polar") {
      return "tonight";
    }
    return screen;
  });

  // A sequence that runs (or waits paused, or on you) is one tap away from any screen:
  // a dot on the Sequences tab, which says how it stands to screen readers too.
  const run = $derived(live.app.sequence?.run ?? null);
  const session = $derived(run && run.state !== "finished" ? run.state : null);
  // Explore and Sequences exclude each other: while one works, the other's tab is
  // dimmed and leads to the one that works.
  const working = $derived(workingView(run, live.app.jobs));
  function blocked(tab: Tab): boolean {
    return (tab === "explore" || tab === "sequence") && working !== null && working !== tab;
  }
  // Something on Rig needs a look, or the owner has updates worth installing: a dot
  // on the Rig tab, since the section that says so may be closed.
  const rig = $derived(live.synced ? rigAttention(live.app, auth.owner) : null);
</script>

<nav class="nav" aria-label={i18n.t.tabs.label}>
  <span class="logo"><Icon name="logo" size={40} /></span>
  <ul>
    {#each TABS as tab (tab)}
      <li>
        <a
          href={href({ screen: blocked(tab) && working ? working : tab })}
          aria-current={tab === current ? "page" : undefined}
          class:blocked={blocked(tab)}
          title={blocked(tab) && working ? i18n.t.tabs.busy(i18n.t.tabs[working]) : undefined}>
          <span class="icon">
            <Icon name={tab} />
            {#if tab === "sequence" && session}
              <span class="badge" class:paused={session === "paused" || session === "pausing"}></span>
            {/if}
            {#if tab === "rig" && rig}
              <span class="badge {rig}"></span>
            {/if}
          </span>
          <span class="name">{i18n.t.tabs[tab]}</span>
          {#if tab === "sequence" && session}<span class="visually-hidden">{i18n.t.session.states[session]}</span>{/if}
          {#if blocked(tab) && working}<span class="visually-hidden">{i18n.t.tabs.busy(i18n.t.tabs[working])}</span>{/if}
          {#if tab === "rig" && rig}<span class="visually-hidden">{i18n.t.rig.tabAttention[rig]}</span>{/if}
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
    color: var(--muted);
    text-decoration: none;
  }
  .icon {
    position: relative;
    display: inline-flex;
  }
  .badge {
    position: absolute;
    top: -2px;
    right: -4px;
    width: 9px;
    height: 9px;
    border-radius: 50%;
    background: var(--accent);
    box-shadow: 0 0 0 2px var(--surface);
  }
  .badge.paused,
  .badge.warning {
    background: var(--warning);
  }
  .badge.problem {
    background: var(--error);
  }
  .name {
    font-size: 13px;
    line-height: 16px;
    font-weight: 500;
    text-align: center;
  }
  /* The current tab differs in weight and in a filled pill, not only in color. */
  a.blocked {
    opacity: 0.45;
  }
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
