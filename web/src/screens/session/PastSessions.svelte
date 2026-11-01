<script lang="ts">
  // The sequences' past runs, newest first, each opening its report (#/session/<id>).
  import Icon from "../../components/Icon.svelte";
  import { listSessions } from "../../lib/api";
  import { formatDateTime } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import { live } from "../../lib/live.svelte";
  import { href } from "../../lib/router.svelte";
  import type { SessionSummary } from "../../lib/types";

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);
  let sessions = $state<SessionSummary[]>([]);

  // Again whenever a run starts or ends.
  const run = $derived(live.app.sequence?.run ?? null);
  const key = $derived(run ? `${run.run}:${run.state === "finished"}` : "");
  $effect(() => {
    void key;
    listSessions(10)
      .then((found) => (sessions = found))
      .catch(() => {});
  });
</script>

{#if sessions.length}
  <section aria-labelledby="past-sessions">
    <h2 id="past-sessions">{t.report.past}</h2>
    <ul>
      {#each sessions as session (session.id)}
        <li>
          <a href={href({ screen: "report", id: session.id })}>
            <span class="text">
              <span class="name">{session.name}</span>
              <span class="muted small">
                {formatDateTime(session.started, locale)} · {session.outcome
                  ? t.session.states[session.outcome]
                  : t.session.states.running}
              </span>
            </span>
            <Icon name="chevronRight" />
          </a>
        </li>
      {/each}
    </ul>
  </section>
{/if}

<style>
  h2 {
    margin: 0 0 var(--space-2);
    font-size: 15px;
    line-height: 22px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--line);
    border-radius: var(--radius-card);
    background: var(--surface);
  }
  li + li {
    border-top: 1px solid var(--line);
  }
  a {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    min-height: 56px;
    padding: var(--space-2) var(--space-4);
    color: var(--text);
    text-decoration: none;
  }
  .text {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }
  .name {
    font-weight: 500;
  }
  .small {
    font-size: 13px;
    line-height: 18px;
  }
</style>
