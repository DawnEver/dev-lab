---
name: one-forge-retry-door-names-a-rate-limit
description: Every forge HTTP exchange now runs through forgefailure.retried; a rate limit is its own retryable class, waited out by Retry-After / X-RateLimit-Reset.
metadata:
  type: project
---
# One forge retry door, and a rate limit is not a refused credential

2026-11-05: GitHub answered `403 API rate limit exceeded`. `Client._diagnosis` measured the 403 against
`GET /user`, which is rate limited too, and reported "the forge refused the stored credential" -- never
retried. A census of every forge call site also found three bypasses of the client's loop: `_raw`
(`download`, `pull_diff`) made one attempt; the Actions artifact protocol (`actionsartifact`) made one
attempt per urllib exchange; `forgesecrets.set_secret` wrapped its OWN loop around the door's, re-sending a
refused Gitea write three times (nine requests) and running `gh` with no classification at all.

Repair: `forgefailure.retried` is the one HTTP loop (the client's JSON calls, its raw reads, the artifact
protocol). `Diagnosis.RATE_LIMITED` (netverb table row above the 403 row) is named before any `GET /user`
measurement: a 429, or a 403 with `X-RateLimit-Remaining: 0`, a `Retry-After`, or a rate-limit body.
`forgefailure.pause` waits the named time, capped at `RATE_WAIT_CAP_S` (60 s); past the cap the call is
reported at once, never slept for an hour. `gh secret set` runs through `run_network_verb`, whose table now
reads gh's `Bad credentials` (refused) and `HTTP 404: Not Found` (absent).

Left outside, by design: `reviewcode.forge_call` and the inline `ci_base.toml` fetch are stdlib-only
(no dev_lab import), and both fail safe to the full review. `forge.call` / `read_rule` /
`apply_protection` have no src caller (tests only) -- dead, a separate removal.
