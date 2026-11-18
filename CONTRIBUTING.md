# Contributing to NOCS

Thanks for your interest! NOCS is at an early stage; please open an issue to
discuss larger changes before sending a pull request.

## Language

Code, comments, commit messages and documentation are written in English.
User-facing strings go through the i18n catalogs (English and Spanish are
maintained from the start).

## Developer Certificate of Origin

NOCS uses the [Developer Certificate of Origin](https://developercertificate.org/)
instead of a CLA. Every commit must be signed off, certifying that you wrote the
change or otherwise have the right to submit it under the project's license
(AGPL-3.0):

```
Signed-off-by: Your Name <your.email@example.com>
```

`git commit -s` adds this line automatically.

## Design documents

[docs/design.md](docs/design.md) and [docs/ux.md](docs/ux.md) describe how NOCS
works; if your change alters that, update them in the same change. The ADRs in
[docs/adr](docs/adr/) are a frozen archive from the project's first weeks and are
no longer written or maintained.
