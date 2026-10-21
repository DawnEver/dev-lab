# PLAN: a short, robust toolchain (user-approved 2026-10-21)

Scope: lab-commons, dev-lab (new), ai-lab, cc-market, cc-config, and every consumer (motronics-studio,
wdg-lab, numerics-lab, optimi-lab). Principles: first principles, no historical baggage, Occam, single
source of truth, layered decoupling, names match, no backward compatibility, progressive disclosure.

## 1. The target in one paragraph

Three layers, dependencies pointing down only. **lab-commons** is the runtime library (units, paths, io,
log, structured, config, credentials, outcomes, viz). **dev-lab** is development AND execution: forge,
hooks, agent guards, family files, rules registry, dependency doors, hpc, compute, box (the one capacity
ledger). **ai-lab** is model access: providers, keys, the call protocol, the review method and its one
merge, session identity. **cc-market** and **cc-config** are thin: Claude Code plugins that call ai-lab /
dev-lab, and this machine's install and settings. Every dependency floats to newest, kept there by
machines, never by hand. One session is one PR per repo, never stacked; the forge syncs, tests, reviews and
merges it; every failure is a status on the PR.

## 2. Root causes (measured 2026-10-21)

| # | cause | evidence |
|---|---|---|
| R1 | the toolchain is a locked dependency of every repo; the serving fleet runs another version than the code under test | a hand relock commit on nearly every push; #244's new table froze the fleet (no host could claim it) |
| R2 | local gates duplicate the forge | 2-3 refusals per plain push; a 310-test pre-commit |
| R3 | heterogeneous fleet; failures only in host logs | Ada QOS discarded a 6 h run; WS2 MAX_PATH trees; diagnosis by ssh |
| R4 | the review spans four repos, machine paths and two merge implementations | `merge.mjs` (cc-market) and `rules.py` (ai-lab) both merge findings; an empty context gave a silent HTTP 400 |
| R5 | configuration in many sources | pyproject tables, machine config, rendered files, cc-config settings, hook TOML |
| R6 | PRs fragment and stack | 28 open motronics PRs; one stalled base blocked a dozen |
| R7 | rule and module sprawl | 62 rules, 231 dev modules, 47 forge modules (~10k lines), size-only splits |
| R8 | agents cannot verify locally | `measure` refused for memory in nearly every agent run |
| R9 | concurrency decided per call site | G memory-starved by parallel runs that each sized themselves |
| R10 | session identity is agent-written | `Claude-Session:` is Claude-only; codex/ccds write none |
| R11 | reference artefacts used as inputs | output/reference decks read by tests and production |

## 3. Metrics

Baseline in P0, re-measured after every phase: median edit->merged; integrator hand actions per PR; share
merged with no human touch; refusals per push and their false-positive share; open PRs; host failures
without a PR status.

## 4. Phases

### P0 baseline
The forge and the hooks log every refusal and every hand action (one JSONL per kind).

### P1 stop the bleeding (in flight)
- Land the 2026-10-21 PRs: lab-commons #236 #237 #242 #243 #244 #246; motronics #4684 #4685 #4660 #4681 then
  the rest; numerics-lab #18; ai-lab #29 #31.
- ONE SESSION, ONE PR per repo. The launcher issues a session id (`LAB_SESSION`) for Claude, codex and ccds;
  the commit-msg hook writes `Lab-Session:`; `forge pr create` and the pre-push of a new `pr/*` refuse a
  second open PR of the same session. Splits only as a counted, reasoned, user-approved exception.
- NO STACKED PRs: every PR is cut from and targets the integration branch.
- Auto-sync (merge the integration branch into a behind head, relock, re-render, push) and auto-merge on.
- A coalesced ref's superseded run is cancelled even if started; a QOS refusal at any round releases or
  waits, never discards.

### P2 the three-layer split, one cut-over
- Before: move `dev._forge_journal.durable_write` to a leaf both compute and forge import; move
  `dev.forgeunit` next to compute; version the box ledger format (one upgrade-on-read owner: a data format,
  not a code shim).
- dev-lab repo (package `dev_lab`, history kept) takes dev, hpc, supervise, compute, box and their helpers
  (~75k lines); lab-commons keeps the runtime (~6.3k lines); `multiprocess` is deleted (no importer).
- Tables that belong to dev-lab are renamed `[tool.dev_lab.*]` in the same merge as the imports; no
  read-time upgrade.
- Cut-over day: forge hosts install dev-lab and switch serving; consumers switch in one merge each
  (numerics-lab, ai-lab, optimi-lab, wdg-lab, motronics); lab-commons releases without the moved modules.
  Superseded heads are not tested with the old tool.
- Versions: the machine tool self-updates each forge tick; a consumer venv carries dev-lab in uv.lock,
  relocked by auto-sync. `dev-lab>=X` rises only in the PR that first uses a new API; a push checks only
  the floor.
- Rendered family files are generated at bootstrap and not committed, except `.gitignore`; the pre-push
  `famfiles` check then goes away.

### P3 shrink local gates
Local keeps irreversible-harm checks (secrets, force push, wrong target) and second-scale format checks;
architecture tests, lock freshness, branch set and merge audit run on the forge only. Every PreToolUse
guard is judged by its measured fire and false-positive rate; style guards become hints or go.

### P4 one model-access engine (ai-lab)
- The sharp-review method data and its ONE merge live in ai-lab; cc-market's sharp-review and fabric call
  ai-lab and keep no logic; cc-config keeps settings, launchers and install only.
- The forge trigger stays in dev-lab; the findings reader moves to ai-lab.
- The forge runs `ai-lab review` from the machine install: no capability paths. One key source. Any failure
  is `tests/review: error` with its reason.
- The session-id launcher lives here and is called by every launch path.

### P5 one capacity truth, a uniform fleet, visible failures
- Concurrency: HOW to run in parallel is the standard library (threads, processes, pools); HOW MUCH may run
  on a machine is the box ledger only. Every fan-out holds a box demand (cores, memory, seats) before it
  spawns; its worker count is derived from the grant; the grant sets the child thread caps
  (OMP/MKL/OPENBLAS). A guard refuses a pool started without a hold.
- One execution profile per OS. Claims check capacity first; a capacity refusal releases, never discards
  finished work. Every host failure is a structured PR status; host logs ship to the forge.
- `forge try <paths>`: an agent's tests run on the fleet on demand, replacing local measure.
- OS is a resource (`@pytest.mark.windows/linux`), never a platform skip. The Windows part runs on a PR only
  when its footprint is reached (carry otherwise) and after the resource parts; integration and main run it
  in full.

### P6 truth in the tree
- TRACKED-CITES-NO-EPHEMERAL: no tracked file (memory included) cites what git ignores or a machine path;
  criterion derived from `.gitignore`; memory rewritten in place (measured numbers inline, a regeneration
  command, or "evidence no longer available").
- Reference decks are provenance prose in cases/ only; a JMAG solve runs only on a deck our builder
  generated, from a content-keyed deck cache; build on miss; what the builder cannot generate refuses.
- Rules record their catches; a rule with none in 30 days is reviewed for deletion; rules pages cite IDs,
  never restate them; forge modules regroup by concept (claim, run, gather, merge, sync); hand registries
  (provenance, adoption, kit floor) become derived.

## 5. Order and risk

P1 first: every later PR stalls on today's chain otherwise. P2 is the largest change; its module list was
measured (no forbidden edge exists today). P3-P6 run alongside P2. The cut-over is one date, no
compatibility layer; the only data the two tool versions share on cut-over day is the box ledger, which is
versioned beforehand.
