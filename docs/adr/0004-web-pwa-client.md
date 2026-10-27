# 0004. Single web PWA client (Svelte + TypeScript)

Date: 2026-10-27 · Status: Accepted

## Context

Users connect from phones, tablets and computers on iOS, Android, Linux, macOS
and Windows. A single maintainer cannot sustain several native apps.

## Decision

One Progressive Web App, written in TypeScript with Svelte, built to static
files and served by nocsd. Native packaging (e.g. Capacitor) is deferred until
there is a concrete need (app store presence, platform APIs).

## Consequences

- One codebase for every platform; no app store friction; updates ship with
  the server.
- Some platform limits (background execution, notifications on iOS) apply.
- Svelte keeps bundles small and fast on low-end phones.
