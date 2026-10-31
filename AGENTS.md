# Roundhouse - AI Agent Instructions

Read `README.md` and `CONTRIBUTING.md` first. They are the source for setup,
code style, and commits.

## Confidentiality

This repository is published at its first release. Do not write internal
planning data into code, comments, commit messages, docs, or configuration:

- No milestone labels, phase numbers, or sprint items.
- No internal spec or section references.
- No names or paths of private repositories or documents.
- No decision-record IDs.

State the technical fact directly. Public-standard references (for example
`RFC 8949 §4.2`) are permitted.

## Private data

Do not write real IP addresses, MAC addresses, Wi-Fi SSIDs, or credentials into
any file, including logs, shell examples, and config snippets. Write
`<redacted>` in place of the value and keep the technical fact.

## Tooling

- Run tools through `mise run <task>`; do not install packages globally.
- Run `mise run check` before a commit.

## Commits

- Subject format: `{area}: {title}`. Areas: `feat`, `fix`, `refactor`, `test`,
  `docs`, `build`.
- One logical change per commit.
- No `Co-Authored-By` trailers.
