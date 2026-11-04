---
name: PLAN-forge-host-roles-are-one-configured-mechanism
description: The hand-written forge-host scripts (promote, break-glass, backup, probe) become one tested dev-lab mechanism, dev_lab.ops, configured by one host file; break-glass is a forge verb authorized per use by a server-verified TOTP code.
metadata:
  type: project
created: 2026-11-03
accessed: 2026-11-03
---

# PLAN: forge host roles are one configured mechanism (user directives 2026-11-03)

Directives: first principles, single source of truth, everything generic -- a deployment is a configuration
instance; daily maintenance involves no human; break-glass is runnable by a LOCAL agent session but only under
the user's per-use authorization, as a forge verb. Revised the same day: NO ssh CA, no certificates, no
second-device signing -- per-use authorization is a TOTP code from the user's Authenticator, verified by the
server.

## What existed (prior art, reused)

| fact | where it already lives | reuse |
|---|---|---|
| host config + alert channels | `dev_lab.supervise.config` (`/etc/dev-lab/supervise.toml`, env overrides) | the ops roles are an `[ops]` table IN THAT FILE; alerts are its `[alerts]` through `supervise.alert.Notifier` |
| health probe | `supervise.components.health.HttpHealth` | the probe role IS a supervise component config -- no new code |
| promotion decision | `dev_lab.dev.integrate.promote` (`decide`: every part PASS at scope full) | the promote role calls it, then pushes the trunk |
| trunk / integration names | `[tool.dev_lab.integrator]` via `lanepolicy.policy_at` | read at `origin/HEAD` of each checkout, never restated |
| forge host, owner, repo | each repo's origin URL (`forgework.client_for`) | the config lists the clone URLs once; all else derived |
| merging a PR at a head | `forgemerge.merge` (both forges, head-pinned) | break-glass merges through it |
| Break-Glass | `dev_lab.dev.breakglass`: the `Break-Glass: <reason>` trailer, `notices()` opens one integration issue per use | the server merge writes that trailer into the merge commit, so the existing notice follows every use |
| nightly promotion | ci_base `promote` job (D48-1A) | a forge whose Actions token cannot push a protected trunk runs the host role instead -- same `integrate promote` |

## Design

- `dev_lab.ops` (package): `config` (schema + load over `supervise.config.load_config`), `totp` (RFC 6238),
  `promote`, `breakglass` (server role), `install` (renders units / sshd drop-in / sudoers into a root),
  `__main__` (the one door: `python -m dev_lab.ops --config <toml> install|promote|breakglass serve|enrol|tick`).
- Config (`[ops]` of the host's supervise.toml): `home`, `python`, `repos` (clone URLs);
  `[ops.promote]` user, schedule, credentials, memory_max; `[ops.breakglass]` account, keys, token, totp,
  state (dir), log, min_reason, issuer, wave_hours, max_merges, tick, remind_hours. No hostnames, owners or repo names in code.
- Promote: per repo, clone if missing, fetch, `integrate promote <origin/<integration>>`, push the trunk with the
  configured credential; a refusal is exit 2 and quiet (nightly no-op is normal), a failure alerts.
- Break-glass WAVES (three rulings the same evening: TOTP not certificates; a code is not bound to the PR the
  human saw, so a code opens a WAVE; acknowledging an audit needs no code and never blocks):
  - `forge breakglass open [--hours H] [--max-merges M]` -- the HUMAN types the Authenticator code; the server
    verifies it (RFC 6238, 30 s, +-1 step, a replayed step refused) and opens a wave bounded by `wave_hours`
    (client may only shorten) and `max_merges` (client may only tighten). One wave open at a time.
  - `forge pr breakglass <N> --reason "..."` -- inside the open wave, no code. Server refuses: no open wave, expired,
    cap reached, unconfigured repo, short reason, PR not open, not into the declared integration branch, head not the
    one shown. Then comments, merges as the configured identity with a `Break-Glass:` trailer, and ANNOUNCES the merge
    itself over `[alerts]` (repo, PR, head, reason, wave id) -- server-originated, so the human sees what merged.
  - On `close` or expiry (the `breakglass tick` timer, or lazily on any request) ONE audit report per wave is
    written (`<state>/waves/<id>.md`) and sent. `forge breakglass ack [ID]` records who/when, no code; an
    unacknowledged audit is reminded once per `remind_hours` and blocks nothing.
  - The secret lives only in a root-only file on the host; `python -m dev_lab.ops ... breakglass enrol` generates it
    and prints the otpauth URI once on the host's terminal.
- Transport choice: ssh forced command, not an HTTP endpoint -- no listening service, no TLS/proxy route to keep,
  the transport identity is in the sshd log, and the agent's ordinary key is what it already has.
- Install: renders into a `--root` (default `/`), idempotent (unchanged file not rewritten), prints what changed;
  `systemctl daemon-reload` and `sshd -t` are the operator's (main session's) step, printed.

## Slices

1. THIS PR: PLAN, config, totp, waves, promote role, break-glass server role + enrol + tick, client verbs, install
   renderer, tests.
2. Backup role: `ops backup export` (forced command) + `ops backup pull` with a pluggable dumper
   (`gitea` + `postgresql` now), retention from config, refuses empty output.
3. Ops troubleshooting account: key + TOTP through PAM (`pam_oath`), rendered by `install` from `[ops.access]`.
4. Probe: the HttpHealth component entries in the probe host's supervise.toml (config only).
