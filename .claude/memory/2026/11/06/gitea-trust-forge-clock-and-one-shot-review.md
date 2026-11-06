---
name: gitea-trust-forge-clock-and-one-shot-review
description: "2026-11-06: only GitHub vets authors and review posters; the forge clock never comes from a pass memo; PR review is a one-shot advisory check (#255 #257 #266 #267 #268, #248 #249 merged)."
metadata:
  type: project
---

# Gitea trust, the forge clock, one-shot review (2026-11-06)

## Trust (user rulings: Gitea is safe; vetting is for GitHub)
- #257 adds `Backend.vets_authors` (GitHub true, Gitea false). `Client.trusts(login)` replaces `can_write` as the
  one trust test for the merge door (`forgemerge.external`) and for cap raises. `_forgeteams` / `writer_unit`
  (#253) are deleted: Gitea's Actions token cannot read team rosters.
- #255 changes `forge_posted(client)` to accept every review status where the backend vets no author; GitHub
  keeps `github_posted`. The Gitea run-path/adoption machinery is deleted. Its first red came from the
  `StateForge` fake: its default manifest was empty, and the gate refuses an empty manifest.

## The forge clock (#266)
- Every client in a poller pass shares one `ReadMemo`. A later client's `whoami` was answered from the memo,
  so no request went out and no Date header came back. `forge_now` raised "answered without a Date header",
  and `prompt()` aborted before the security step on every tick, so no Gitea PR ever got `tests/security`.
  `forge_now`'s ask now bypasses the memo. Caddy itself sends Date on every endpoint.

## One-shot advisory review (#267, open at 18:10Z, tests green on both OSes)
- Before: every head was a round, HIGH blocked the merge, the cap text said "split the PR", and a reviewer
  `error` was never waived.
- "diff unsupported": an oversize head became one path-less WHOLE slice. ai-lab renders that slice in agent
  mode, which the headless runner cannot run, so every reviewer returned unsupported.
- After:
  - one review per PR, run again on 2x growth or `forge review again`;
  - findings are advice; only security blocks;
  - a review that cannot run retries once, then merges `Unreviewed:`;
  - every slice names its paths.
- Deleted: rounds, dispose/adjudicate/judge, the held/blocked verbs, the round cap, review-claims.yml.
- User rule: never split a PR for the reviewer (one session, one task, one PR).
- Follow-ups: `tests/review-hold` is still read; the judge-host waiver; re-render consumers.

## Smaller
- #248 merged: uvfollow, inventoried and declared original; its test paths name no home directory.
- #249 merged: one retry door; its test matches "REFUSED", not "404".
- #268 (open): `EXCLUDED_IN_TEMP` takes a glob, `claude-notif-*.ps1` (the harness's own file).
- `supervise/deploy.py:52` hard-codes `/var/tmp`, which lands as `C:\var\tmp` on Windows (not fixed yet).
