<script lang="ts">
  // A role's driver in the profile editor: one field to type in and choose from the
  // list right under it (WAI-ARIA combobox with a listbox). The field shows the
  // current choice; typing filters the list, the role's own catalog groups first,
  // and the first match is active, so Enter takes it. A tap or a click on an option
  // chooses it too. Leaving the field without choosing keeps the choice it had.
  import { tick, untrack } from "svelte";
  import { moveActive } from "../lib/combobox";
  import { driverOptions, type DriverChoice } from "../lib/drivers";
  import { i18n } from "../lib/i18n";
  import Icon from "./Icon.svelte";

  let {
    label,
    context,
    choices,
    groups,
    current,
    onchoose,
    autofocus = false,
  }: {
    label: string;
    // What the field is for (the role), in its accessible name: every role's field is "Driver".
    context?: string;
    choices: readonly DriverChoice[];
    // The role's catalog groups, offered first.
    groups: readonly string[];
    current: DriverChoice | null;
    onchoose: (choice: DriverChoice) => void;
    // Focus the field and open the list when it appears (a role just added).
    autofocus?: boolean;
  } = $props();

  const id = $props.id();
  const t = $derived(i18n.t);
  const name = $derived(context ? `${context}: ${label}` : label);

  let field = $state<HTMLElement>();
  let input = $state<HTMLInputElement>();
  let listbox = $state<HTMLElement>();
  let open = $state(false);
  // What was typed; null while the field shows the current choice.
  let query = $state<string | null>(null);
  let active = $state(-1);

  const options = $derived(driverOptions(choices, groups, query ?? "", current));
  const flat = $derived(options.flatMap((group) => group.choices));
  const indexOf = $derived(new Map(flat.map((choice, index) => [choice.key, index])));
  const text = $derived(query ?? current?.text ?? "");

  // The list just opened on the current choice: it shows it in its middle.
  let centre = false;
  // The mouse made the option active: it is in sight already, and scrolling the list
  // under the mouse would make another one active.
  let pointed = false;

  function show(): void {
    if (!open) {
      centre = query === null;
      requestAnimationFrame(fit);
    }
    open = true;
    // Typed: the first match. Not typed: the current choice, where the list starts.
    active = query === null ? flat.findIndex((choice) => choice.key === current?.key) : flat.length > 0 ? 0 : -1;
  }

  function close(): void {
    open = false;
    query = null;
    active = -1;
  }

  function choose(choice: DriverChoice): void {
    if (choice.key !== current?.key) onchoose(choice);
    close();
    // Chosen by a key, the field keeps the focus: typing again starts a new search.
    void tick().then(() => {
      if (document.activeElement === input) input?.select();
    });
  }

  function oninput(event: Event & { currentTarget: HTMLInputElement }): void {
    query = event.currentTarget.value;
    show();
    // Another list: from its top.
    if (listbox) listbox.scrollTop = 0;
  }

  function onkeydown(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      if (!open && query === null) return;
      event.preventDefault();
      close();
      return;
    }
    if (event.key === "Enter") {
      // Never submits the form while choosing.
      if (!open && query === null) return;
      event.preventDefault();
      const choice = flat[active];
      if (choice) choose(choice);
      return;
    }
    if (!open) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        show();
      }
      return;
    }
    const next = moveActive(event.key, active, flat.length);
    if (next === null) return;
    event.preventDefault();
    active = next;
  }

  function clear(): void {
    query = "";
    input?.focus();
    show();
  }

  // The list in sight as it opens: on a phone the field goes to the top of the screen,
  // above the keyboard that comes up; elsewhere only when the list would end off
  // the screen (or under the tab bar).
  function fit(): void {
    if (!open || !field || !listbox) return;
    const view = window.visualViewport?.height ?? window.innerHeight;
    const touch = window.matchMedia("(pointer: coarse)").matches;
    if (!touch && listbox.getBoundingClientRect().bottom <= view - TAB_BAR) return;
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    field.scrollIntoView({ block: "start", behavior: still ? "auto" : "smooth" });
  }

  // The tab bar at the bottom of a phone's screen, and a group's label stuck at the
  // top of the list: options are not in sight under them.
  const TAB_BAR = 64;
  const GROUP_LABEL = 34;

  // The active option stays in sight as the keys move it, scrolling the list alone
  // (never the page).
  $effect(() => {
    if (!open || active < 0 || !listbox) return;
    const option = listbox.querySelector<HTMLElement>(`#${CSS.escape(`${id}-${active}`)}`);
    if (!option) return;
    if (pointed) {
      pointed = false;
      return;
    }
    const top = option.offsetTop - GROUP_LABEL;
    const bottom = option.offsetTop + option.offsetHeight;
    if (centre) {
      centre = false;
      listbox.scrollTop = option.offsetTop - (listbox.clientHeight - option.offsetHeight) / 2;
    } else if (top < listbox.scrollTop) listbox.scrollTop = top;
    else if (bottom > listbox.scrollTop + listbox.clientHeight) listbox.scrollTop = bottom - listbox.clientHeight;
  });

  $effect(() => {
    if (!autofocus || !input) return;
    untrack(() => {
      input?.focus();
      show();
    });
  });

</script>

<div class="field" bind:this={field}>
  <label class="label" for={id}>{label}</label>
  <div class="control" class:open>
    <Icon name="search" size={20} />
    <input
      {id}
      bind:this={input}
      type="text"
      role="combobox"
      autocomplete="off"
      autocapitalize="off"
      spellcheck={false}
      enterkeyhint="done"
      aria-autocomplete="list"
      aria-expanded={open}
      aria-controls="{id}-list"
      aria-activedescendant={open && active >= 0 ? `${id}-${active}` : undefined}
      aria-label={context ? name : undefined}
      aria-describedby={current && !open ? `${id}-driver` : undefined}
      placeholder={t.editor.driverPlaceholder}
      value={text}
      {oninput}
      {onkeydown}
      onfocus={() => input?.select()}
      onclick={() => {
        if (open) return;
        show();
        input?.select();
      }}
      onblur={close} />
    {#if text}
      <button
        type="button"
        class="clear"
        aria-label={t.editor.clearDriver}
        onmousedown={(event) => event.preventDefault()}
        onclick={clear}>
        <Icon name="close" size={20} />
      </button>
    {/if}
  </div>
  {#if current && !open}
    <p class="hint mono" id="{id}-driver">{current.driver}</p>
  {/if}
  <!-- Options are not focusable: a press keeps the focus in the field, so it does not close the list before the click. -->
  <div
    class="list"
    id="{id}-list"
    role="listbox"
    aria-label={name}
    tabindex="-1"
    hidden={!open}
    bind:this={listbox}
    onmousedown={(event) => event.preventDefault()}>
    {#if open}
      {#each options as group, g (group.group)}
        <div class="group" role="group" aria-labelledby="{id}-group-{g}">
          <div class="group-label" role="presentation" id="{id}-group-{g}">
            {group.group ?? t.editor.otherDrivers}
          </div>
          {#each group.choices as choice (choice.key)}
            {@const index = indexOf.get(choice.key) ?? -1}
            <!-- The field handles the keys. -->
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <div
              class="option"
              class:active={index === active}
              id="{id}-{index}"
              role="option"
              tabindex="-1"
              aria-selected={choice.key === current?.key}
              onpointermove={() => {
                if (index === active) return;
                pointed = true;
                active = index;
              }}
              onclick={() => {
                choose(choice);
                // A tap closes the phone's keyboard; a key goes on in the field.
                input?.blur();
              }}>
              <span class="model">{choice.text}</span>
              {#if choice.text !== choice.driver}
                <span class="detail">
                  {#if choice.manufacturer}{`${choice.manufacturer} · `}{/if}<span class="mono">{choice.driver}</span>
                </span>
              {/if}
              {#if choice.key === current?.key}<span class="check"><Icon name="check" size={20} /></span>{/if}
            </div>
          {/each}
        </div>
      {:else}
        <p class="empty">{query?.trim() ? t.editor.noDriver(query) : t.editor.noDrivers}</p>
      {/each}
    {/if}
  </div>
  <!-- Always there: a live region added with its text may not be announced. -->
  <span class="visually-hidden" role="status">{open ? t.editor.driverMatches(flat.length) : ""}</span>
</div>

<style>
  .field {
    scroll-margin-top: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }
  .label {
    color: var(--muted);
    font-size: 15px;
    font-weight: 500;
  }
  .control {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-height: var(--primary-height);
    padding-left: var(--space-4);
    border-radius: var(--radius-button);
    border: 1px solid var(--line);
    background: var(--surface);
    color: var(--muted);
  }
  .control:focus-within {
    border-color: var(--accent);
  }
  .control.open {
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  input {
    flex: 1;
    min-width: 0;
    min-height: var(--primary-height);
    padding: 0 var(--space-4) 0 0;
    border: 0;
    background: transparent;
    color: var(--text);
    font-size: 17px;
    text-overflow: ellipsis;
    outline: none;
  }
  .clear {
    flex: none;
    display: grid;
    place-items: center;
    width: var(--primary-height);
    height: var(--primary-height);
    margin-left: calc(-1 * var(--space-4));
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  .hint {
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
    overflow-wrap: anywhere;
  }
  .list {
    position: relative;
    /* Under the field, in the page's flow: never clipped, and the page scrolls past it. */
    max-height: min(360px, 50vh);
    margin-top: calc(-1 * var(--space-2) - 1px);
    overflow-y: auto;
    overscroll-behavior: contain;
    border: 1px solid var(--accent);
    border-top-color: var(--line);
    border-radius: 0 0 var(--radius-button) var(--radius-button);
    background: var(--surface);
  }
  .list[hidden] {
    display: none;
  }
  .group-label {
    position: sticky;
    top: 0;
    z-index: 1;
    padding: var(--space-2) var(--space-4);
    background: var(--raised);
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
    font-weight: 600;
  }
  .option {
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: center;
    column-gap: var(--space-2);
    min-height: var(--touch);
    padding: var(--space-2) var(--space-4);
    cursor: pointer;
  }
  .option.active {
    background: var(--raised);
    box-shadow: inset 3px 0 0 var(--accent);
  }
  .model {
    grid-column: 1;
    font-size: 17px;
    line-height: 24px;
    overflow-wrap: anywhere;
  }
  .detail {
    grid-column: 1;
    color: var(--muted);
    font-size: 13px;
    line-height: 18px;
    overflow-wrap: anywhere;
  }
  .check {
    grid-column: 2;
    grid-row: 1 / span 2;
    color: var(--accent);
  }
  .empty {
    margin: 0;
    padding: var(--space-3) var(--space-4);
    color: var(--muted);
    font-size: 15px;
  }
</style>
