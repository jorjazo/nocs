<script lang="ts">
  // The SER files recorded, newest first: what each holds, frames it lost on the way
  // (a drive too slow for the camera) or why NOCS stopped it, with download and
  // delete. Large files: downloading them over Wi-Fi takes a while; taking the drive
  // home is often quicker.
  import Banner from "../../components/Banner.svelte";
  import ConfirmButton from "../../components/ConfirmButton.svelte";
  import Icon from "../../components/Icon.svelte";
  import { deleteRecording, recordingUrl } from "../../lib/api";
  import { formatBytes, formatDateTime, formatDecimal, formatPlain, formatSeconds } from "../../lib/format";
  import { i18n } from "../../lib/i18n";
  import type { VideoRecording } from "../../lib/types";
  import { droppedShare } from "../../lib/video";

  let {
    recordings,
    owner,
    run,
  }: {
    recordings: VideoRecording[];
    owner: boolean;
    run: (action: () => Promise<unknown>) => Promise<void>;
  } = $props();

  const t = $derived(i18n.t);
  const locale = $derived(i18n.locale);

  function detail(r: VideoRecording): string {
    return t.video.recordingDetail(
      formatPlain(r.frames, locale),
      formatSeconds(r.seconds, locale),
      r.fps === null ? "—" : formatDecimal(r.fps, locale, 1),
      formatBytes(r.size, locale),
    );
  }

  function dropped(r: VideoRecording): string | null {
    const share = droppedShare(r.frames, r.dropped);
    if (share === null || share < 0.02 || r.dropped === null) return null;
    return t.video.dropped(formatPlain(r.dropped, locale), `${formatDecimal(share * 100, locale, 0)} %`);
  }
</script>

<section class="recordings" aria-label={t.video.recordings}>
  <h2 class="caption muted">{t.video.recordings}</h2>
  {#if recordings.length === 0}
    <p class="caption muted">{t.video.noRecordings}</p>
  {:else}
    <ul>
      {#each recordings as r (r.id)}
        {@const lost = dropped(r)}
        <li>
          <div class="head">
            <span class="name mono">{r.name}</span>
            <span class="caption muted">{formatDateTime(r.started, locale)}</span>
          </div>
          <span class="caption">
            {r.width ?? "?"} × {r.height ?? "?"} · {t.video.bits(r.depth ?? 8)} · {formatSeconds(r.exposure, locale)}
            {#if r.gain !== null}· {t.video.gain} {formatPlain(r.gain, locale)}{/if}
            {#if r.filter}· {r.filter}{/if}
          </span>
          <span class="caption muted">{detail(r)}</span>
          <span class="caption muted">{r.destination_label}: {r.path}</span>
          {#if lost}<Banner icon="alert" tone="warning">{lost}</Banner>{/if}
          {#if r.stopped}<p class="caption warning">{t.video.stopped[r.stopped]}</p>{/if}
          <div class="actions">
            <a class="small" href={recordingUrl(r.id)} download={r.name}>
              <Icon name="download" size={18} />
              {t.video.download}
            </a>
            {#if owner}
              <ConfirmButton
                label={t.video.delete}
                confirmLabel={t.video.deleteConfirm}
                onconfirm={() => void run(() => deleteRecording(r.id))} />
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .recordings {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
  h2 {
    margin: 0;
    font-weight: 600;
  }
  ul {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    margin: 0;
    padding: 0;
    list-style: none;
  }
  li {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    padding: var(--space-2) 0;
    border-top: 1px solid var(--line);
  }
  .head {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    flex-wrap: wrap;
  }
  .name {
    overflow-wrap: anywhere;
    font-weight: 600;
  }
  .actions {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }
  .small {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-height: var(--touch);
    padding: 0 var(--space-3);
    border: 1px solid var(--line);
    color: var(--accent);
    font-size: 15px;
    font-weight: 600;
    text-decoration: none;
  }
  .warning {
    color: var(--warning);
  }
  p {
    margin: 0;
  }
</style>
