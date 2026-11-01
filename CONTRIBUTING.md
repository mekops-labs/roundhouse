# Contributing

## Commits

- Subject format: `{area}: {title}`. Areas: `feat`, `fix`, `refactor`, `test`,
  `docs`, `build`.
- Make one logical change in each commit.
- Write one `- bullet` for each changed item when a commit holds several.
- Do not add `Co-Authored-By` trailers.

## Code

- Run `mise run check` before every commit.
- Format and lint with `ruff`. Type-check with `mypy --strict`.
- Keep a comment to one line, three lines at most.
- Run blocking work in the executor. A blocking-call warning fails a test.
- Access an unstable Home Assistant internal from one module only.

## Trying it by hand

`tools/rig/` starts a throwaway Home Assistant and Mosquitto in Podman, with the
integration mounted read-only. Nothing in it is shipped or used by the tests;
its state lives in `~/.cache/roundhouse-dev/rig`.

```sh
mise run rig -- up            # containers, waits until Home Assistant answers
mise run rig -- onboard       # owner, token, MQTT integration
mise run double -- tender &   # a device double: tender or wall
mise run rig -- confirm       # accept the discovered device
mise run rig -- seed          # demo states and a dashboard (--scenario overflow)
mise run rig -- shot          # screenshot the Roundhouse panel (Playwright container)
mise run rig -- logs
mise run rig -- down
```

## Soak and measurements

`tools/soak/` runs two device doubles against a Home Assistant and a Mosquitto
that applies the ACL of `docs/mosquitto-acl.example`. State lives in
`~/.cache/roundhouse-dev/soak`; the rig and the soak can run side by side.

```sh
mise run soak -- --minutes 20      # a short run with restarts of both
mise run soak -- --minutes 1440    # the 24-hour soak
mise run measure                   # the latency budgets, into docs/measurements.md
```

The soak fails on a lost update, an unanswered command, a blocking-call warning,
a Roundhouse error in the log, or a state that disagrees with Home Assistant at
the end. It writes `report.json` to the soak directory.

## Documentation

- Write one instruction in each sentence.
- Use the imperative for procedure steps.
- Name the exact file, command, or value.
- Do not record real IP addresses, MAC addresses, SSIDs, or credentials in any
  file.

## Confidentiality

This repository is private until its first release. Do not write internal
planning data into code, comments, commit messages, docs, or configuration:

- No milestone labels, phase numbers, or sprint items.
- No internal spec or section references.
- No names or paths of private repositories or documents.

State the technical fact directly. Public-standard references are permitted.
