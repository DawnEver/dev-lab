---
name: Actions measurements keep their selection and never post a part
description: A pinned focused Actions measurement uses the canonical verify door and evidence owner without claiming a full part, review, merge or promotion.
metadata:
  type: project
---

Learn-lab issue 36 exposed a real mechanism gap: its existing hosted full-base jobs reached their unchanged 3600-second wall without a parseable terminal test summary. Early failure dots were not semantic RED. A local focused request could not admit its unchanged 5.25 GB claim. Installed dev-lab bc556 and fresh canonical integration 34e79a270e3b40aec2e89ed969c82531a9021884 both offered only smoke/pr dispatch inputs and full jobparts production, not a hosted focused measurement. A forge request selection requires a serve host; it is not an Actions input.

The independent clone lives under the integrator's own ignored output/logs/26/11/15/integration/provider-point-domain/dev-lab. No PRIMARY checkout, provider source or uv cache was edited. Initial clone checkout hit Windows long paths; the retry wrapper actually exhausted three attempts. In this fresh clone only, core.longpaths was enabled, the initial empty index filled with read-tree HEAD, and checkout-index filled only the two missing files, without force or overwriting existing files. Tracked bytes then matched HEAD. A future fresh clone can pass clone's supported -c core.longpaths=true option through the network wrapper. No global Git setting was changed.

The official frozen bootstrap first refused a cross-worktree cwd that identified another checkout; rerunning the same door with the new clone as cwd created only its own .venv. The full installed environment key was b1f371f11d1d5b8c; the canonical verdict key below is 3e097177ca1547d2 because that owner excludes the project under test. Normal hooks were installed. Dependencies and uv.lock were not hand-edited or floated.

The family ci_base.toml now declares measurement_paths (a JSON array of file/node selectors) and measurement_sha (the exact dispatched 40-hex SHA). Either field selects the measurement mode; half-filled input fails closed rather than falling through to full parts. The renderer AND-isolates every normal job, including consumer-added jobs, and the PR concurrency group cannot cancel a PR on a measurement dispatch. The existing Ubuntu runner and shared setup remain; only the measurement checkout disables persisted credentials. This job installs the normal hooks because verify measurements require them, whereas part producers intentionally do not. Normal parts' argv, setup and authority remain unchanged.

jobmeasure validates the event, mixed PR/smoke modes, SHA/HEAD agreement, nonempty JSON selectors, declared test roots, committed file bytes and escaping symlinks. It retains ::node and parameter IDs as argv data, never shell source. The canonical verify door retains every worker, memory, wait and wall default. Producer/outcome and GitHub token variables are not passed to the child; a consumer attempting to give this job write authority or a secret-bearing setup is refused. No tests/base status, review, merge or promote is produced.

The dated artifact directory is an exact allowlist: receipt.json, original stdout.log, and a proved verify.log. There is no environment dump, workspace, .git, cache or user-config upload. The initial receipt is explicitly inconclusive. Invalid unvalidated input is not copied into it. Canonical run_key, EXIT_CODES and verify_log own the actual tree/environment/selector and conclusion; no second verdict parser or schema is introduced. Nested verify controls can write additional logs, so evidence is selected by the exact canonical identity, never by guessing the newest log or requiring the directory to contain one file. Missing, corrupt, ambiguous, mismatched or truncated evidence cannot become PASS, even after exit zero. A killed job may leave only its initial receipt and partial stdout; upload after a whole-job kill is not guaranteed.

Actual TDD receipts under output/logs/26/11/15/verify/:

- verify-20261115T033930Z.log: first tests-only 26 items, 25 failed (missing capability and dispatch fields); lint/format findings were also recorded.
- verify-20261115T034202Z.log: expanded tests-only 30 items, 29 failed, before production implementation.
- verify-20261115T034701Z.log: first full 174 items, 17 failed. Existing predicate expectations needed the additional AND guard, the synthetic byte-exact checkout needed explicit LF on Windows, and three original Bash controls had no Bash on PATH. No assertion or acceptance bar was removed.
- verify-20261115T035350Z.log: 174/0 after those fixes, with the actual Git Bash bin on the invocation's PATH, not a global configuration change. This was not the final qualification: reading its real lowercase canonical verdict exposed an uppercase fake-log premise.
- verify-20261115T035636Z.log: stronger canonical-case, identity-mismatch, input-disclosure and setup-authority plants: 43 items, 17 failed. The fake now uses the real writer's lowercase result and production delegates to canonical EXIT_CODES/run_key/verify_log.
- verify-20261115T035856Z.log: seven complete owner files, 309/0.
- verify-20261115T040243Z.log: actual missing hook-install workflow plant, 2 items / 1 failed; no production change preceded this RED.
- verify-20261115T040605Z.log: nested-log positive controls plus the hook plant, 55 items / 4 failed (and a separately recorded test-signature lint finding). The fix preserves matching proof and rejects unknown evidence, not the original controls.
- Final verify-20261115T040910Z.log: 321/0 across complete jobmeasure, ciworkflows, ciworkflows_merge, ciworkflows_prune, jobparts, forgerequest_paths and verify files.
- Final verify-20261115T041415Z.log: 133/0 across complete actions_alone, famfiles, rendergoldens, prcontinue, review_last_gate, reviewruntime, forgereview_batch, relock and arch_every_forge_call_is_retried files.

Both final runs used one frozen source snapshot (tree sha256:6fd330bc3b331fa6+tracked:c84d4b2f3594a3a7) and verdict environment 3e097177ca1547d2. Counts include each run's family sentinel, not additive unique-suite totals. Official ciworkflows check, rendergoldens check, whole-repo Ruff and format checks passed. Official rendergoldens update moved only github_plain and github_overrides ci.yml fixtures; Gitea and all unrelated renders stayed unchanged. These are workflow snapshots, not numerical goldens.

This is a local independently qualified mechanism change, not evidence of hosted execution or a learn-lab semantic RED. The parent integrator owns normal publication, provider kit sync/render, and an actual same-SHA Actions measurement. No push, external review, vendor action, new host or provider production edit was performed here. The documented dispatch must not be used on an old consumer workflow that lacks these inputs.
