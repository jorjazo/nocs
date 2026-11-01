<script lang="ts">
  // Shell: decides from /api/auth whether to show first run, pairing or the
  // app, keeps the state channel open while allowed, and lays out the tabs.
  import Banner from "./components/Banner.svelte";
  import Button from "./components/Button.svelte";
  import EmptyState from "./components/EmptyState.svelte";
  import NavBar from "./components/NavBar.svelte";
  import { reportClock } from "./lib/api";
  import { auth } from "./lib/auth.svelte";
  import { errorText } from "./lib/errors";
  import { formatDuration } from "./lib/format";
  import { i18n } from "./lib/i18n";
  import { live } from "./lib/live.svelte";
  import { router } from "./lib/router.svelte";
  import { boxSetup } from "./lib/setup.svelte";
  import AuthScreen from "./screens/AuthScreen.svelte";
  import BoxSetup from "./screens/BoxSetup.svelte";
  import ChartPreview from "./screens/dev/ChartPreview.svelte";
  import Dev from "./screens/dev/Dev.svelte";
  import Focus from "./screens/focus/Focus.svelte";
  import Guiding from "./screens/guiding/Guiding.svelte";
  import Live from "./screens/live/Live.svelte";
  import Placeholder from "./screens/Placeholder.svelte";
  import ProfileEditor from "./screens/ProfileEditor.svelte";
  import Rig from "./screens/Rig.svelte";
  import Session from "./screens/session/Session.svelte";

  const t = $derived(i18n.t);
  void auth.refresh();

  const role = $derived(auth.status?.role ?? null);
  const view = $derived.by(() => {
    const status = auth.status;
    if (!status) return auth.error ? "unreachable" : "loading";
    if (status.setup_required) return "setup";
    if (status.role === null || (auth.wantsPair && status.role !== "owner")) return "pair";
    return "app";
  });

  // The state channel is open whenever this client may watch.
  $effect(() => {
    if (role) live.start();
    else live.stop();
  });
  // Revoked (4401): ask where we stand and show pairing; never retry blindly.
  $effect(() => {
    if (live.status === "revoked") void auth.onRevoked();
  });
  // Handshakes refused or failing: maybe this device lost its pairing.
  $effect(() => {
    if (live.failures > 0) void auth.refresh();
  });

  // Every time the state channel opens, the owner's device reports its clock:
  // the server corrects its own timestamps when the Pi's is off, and sets the
  // mount's (ADR 0015). Observers may not.
  $effect(() => {
    if (live.status === "open" && auth.owner) void reportClock().catch(() => {});
  });
  const clock = $derived(live.app.clock ?? null);

  // Phones suspend pages; reconnect as soon as the page is visible again.
  $effect(() => {
    const wake = () => {
      if (document.visibilityState === "visible") live.wake();
    };
    document.addEventListener("visibilitychange", wake);
    return () => document.removeEventListener("visibilitychange", wake);
  });

  const offline = $derived(live.synced && live.status !== "open");
  // On the appliance, the access point's default password goes before anything else
  // (ADR 0028); the flow stays up after saving until its instructions are read.
  const setupBox = $derived(
    auth.owner && (live.app.network?.ap_default_password === true || boxSetup.done !== null),
  );
  // Live view uses the whole width: the preview is edge to edge.
  const full = $derived(router.route.screen === "live");
</script>

{#if view === "loading"}
  <p class="splash muted" role="status">{t.boot.loading}</p>
{:else if view === "unreachable"}
  <main class="standalone">
    <EmptyState icon="offline" title={t.boot.unreachable} body={auth.error?.network ? t.boot.unreachableBody : errorText(auth.error, t)}>
      {#snippet action()}
        <Button variant="primary" onclick={() => auth.refresh()}>{t.boot.retry}</Button>
      {/snippet}
    </EmptyState>
  </main>
{:else if view === "setup" || view === "pair"}
  <AuthScreen mode={view} />
{:else if setupBox}
  <BoxSetup />
{:else if router.route.screen === "focus"}
  <!-- Guided flows take the whole screen, without the tabs (docs/ux.md §1). -->
  <Focus {offline} />
{:else if router.route.screen === "guiding"}
  <Guiding {offline} />
{:else}
  <NavBar />
  <main class="content" class:full>
    {#if offline}
      <div class="banner"><Banner icon="offline" tone="warning">{t.link.offline}</Banner></div>
    {/if}
    {#if clock?.corrected && clock.offset !== null}
      <div class="banner">
        <Banner icon="alert" tone="warning">
          {clock.offset > 0 ? t.clock.behind(formatDuration(clock.offset)) : t.clock.ahead(formatDuration(clock.offset))}
        </Banner>
      </div>
    {/if}
    {#if role === "observer"}
      <div class="banner">
        <Banner icon="eye">
          {t.link.observer}
          {#snippet action()}
            <Button variant="text" onclick={() => (auth.wantsPair = true)}>{t.link.pair}</Button>
          {/snippet}
        </Banner>
      </div>
    {/if}
    {#if router.route.screen === "rig"}
      <Rig />
    {:else if router.route.screen === "live"}
      <Live />
    {:else if router.route.screen === "session"}
      <Session />
    {:else if router.route.screen === "dev"}
      <Dev />
    {:else if router.route.screen === "chart"}
      <ChartPreview />
    {:else if router.route.screen === "profile"}
      {#key router.route.id}<ProfileEditor id={router.route.id} />{/key}
    {:else}
      <Placeholder tab={router.route.screen} />
    {/if}
  </main>
{/if}

<style>
  .splash {
    display: grid;
    place-items: center;
    min-height: 100dvh;
  }
  .standalone {
    padding: 0 var(--margin);
  }
  .content {
    max-width: 760px;
    margin: 0 auto;
    padding: env(safe-area-inset-top) var(--margin) calc(var(--tabbar-height) + env(safe-area-inset-bottom) + var(--space-6));
  }
  .banner {
    position: sticky;
    top: var(--space-2);
    z-index: 5;
    margin-top: var(--space-3);
  }
  .full {
    max-width: none;
    padding: 0 0 calc(var(--tabbar-height) + env(safe-area-inset-bottom));
  }
  .full .banner {
    margin: 0;
    padding: var(--space-2) var(--margin) 0;
  }
  @media (min-width: 768px) {
    .content {
      padding: var(--space-4) var(--space-8) var(--space-8);
      margin-left: max(var(--rail-width), calc((100vw - 760px) / 2));
      margin-right: auto;
    }
    .full {
      padding: 0;
      margin-left: var(--rail-width);
    }
  }
</style>
