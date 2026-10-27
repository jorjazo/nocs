# 0009. Monorepo, English for code and docs

Date: 2026-10-27 · Status: Accepted

## Context

A single maintainer develops server, system helper, web client, packaging and
docs that change together. The project aims at an international community;
the maintainer's language is Spanish.

## Decision

- One repository (`jorjazo/nocs`) containing all components.
- Code, comments, commits and documentation in English.
- The UI is internationalized from the start, with English and Spanish
  maintained.

## Consequences

- Cross-component changes are atomic; one CI pipeline.
- Spanish-speaking users get a first-class UI without blocking international
  contributors.
