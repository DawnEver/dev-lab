# PLAN: a short, robust toolchain (user-approved 2026-10-21)

Scope: lab-commons, ai-lab, cc-market, cc-config. Principles: first principles, no historical baggage,
Occam, single source of truth, layered decoupling, names match, no backward compatibility.

## Root causes (each measured on 2026-10-21)

| # | cause | evidence |
|---|---|---|
| R1 | the dev toolchain is a LOCKED DEPENDENCY of every repo, so every tool change costs N relocks and the serving fleet runs another version than the code under test | nearly every push needed a hand relock commit; PR #244 added a config table the serving kit refuses, so no host could claim it |
| R2 | too many local gates, most duplicating the forge (PreToolUse guards, 310-test pre-commit, commit-msg, pre-push lock/branchset/cz/gate) | a plain push routinely met 2-3 refusals |
| R3 | heterogeneous fleet, failures visible only in host logs | Ada QOS submit limit threw away a 6 h run; WS2 MAX_PATH trees; diagnosis needed ssh / serve.log |
| R4 | the PR review spans four repos and machine paths | ai_lab.python + sharp_review.path capabilities, a runtime worktree, a provider cache; an empty context gave a silent HTTP 400 |
| R5 | configuration in many sources (pyproject tables, machine config, rendered family files, cc-config settings, hook TOML) | config "sync" gates; drift of rendered files |
| R6 | PRs fragment and stack | 28 open motronics PRs; one stalled base blocked a dozen stacked PRs |
| R7 | rule and module sprawl | 62 rules, 231 dev modules, 47 forge modules ~10k lines, size-only splits |
| R8 | agents cannot verify locally | `measure` refused for memory in nearly every agent run |

## Metrics (P0 measures the baseline; every phase re-measures)

Median edit->merged time; integrator hand actions per PR; share of PRs merged with no human touch;
refusals per push and their false-positive share; open PRs.

## Phases

- **P0 baseline.** The forge and the hooks log every refusal and every hand action.
- **P1 stop the bleeding.** Land the 2026-10-21 PRs. ONE SESSION, ONE PR per repo: the session id is issued by
  the launcher (Claude, codex, ccds alike), written as a trailer by the commit-msg hook, checked at
  `forge pr create` and at pre-push of a new `pr/*`; never the agent-written `Claude-Session:` line. NO
  STACKED PRs: every PR is cut from and targets the integration branch. Auto-sync and auto-merge on.
- **P2 split the toolchain from the library.** `lab-commons` keeps the runtime library (units, paths, io,
  log, viz) as an ordinary locked dependency. The dev toolchain (forge, hooks, guards, famconfig, hpc) is ONE
  install per machine with ONE version; a repo declares a minimum version only. A tool change needs no
  consumer commit; the forge always reads a declaration with its own version. Rendered family files are
  generated at bootstrap and not committed, except `.gitignore`.
- **P3 shrink local gates.** Local keeps only irreversible-harm checks (secrets, force push, wrong target) and
  second-scale format checks; architecture tests, lock freshness, branch set and merge audit run on the
  forge. Each PreToolUse guard is judged by its measured fire and false-positive rate.
- **P4 the review is one artifact.** The method ships with or is pinned by ai-lab; the forge runs
  `ai-lab review` from the toolchain install; one key source; any failure is `tests/review: error` with its
  reason.
- **P5 a uniform fleet and visible failures.** One execution profile per OS; claims check capacity first;
  a capacity refusal releases, never discards finished work; every host failure is a structured PR status
  and host logs ship to the forge; `forge try <paths>` replaces local measure for agents.
- **P6 prune by measured value.** Every rule records its catches; a rule with none in 30 days is reviewed for
  deletion; forge modules regroup by concept (claim, run, gather, merge, sync); hand registries (provenance,
  adoption, kit floor) become derived.

## Order and risk

P1 first (otherwise every later PR stalls on the same chain). P2 is the largest change and its module split
list goes to the user before code. P3-P6 run alongside P2. No compatibility layer: one cut-over date.
