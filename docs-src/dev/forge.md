# The forge

The forge (a self-hosted Gitea, or GitHub) is where every verdict lives. A pushed sha that lacks a
`tests/<part>` status is work; a `forge serve` host claims it, runs the suite once and posts the result.
You push, then read `python -m lab_commons.dev.forge queue` or `forge status list <sha>`. You never run a full
suite to learn whether a sha is green, and you never wait for one to push.

## Parts

- **A part** is one NEED-SET's result for one sha, posted as the commit status `tests/<part>`:
  `success` is PASS, `failure` is FAIL, `pending` is a claim. The description is
  `scope=<full|incremental> ran=<n> hands=<part>:<n>,...`; `target_url` links the run record.
- **Parts are derived, never declared** ([parts by need-set](hpc.md#parts-by-need-set)). A test marks the
  resources it needs; its part is that set, named sorted and `+`-joined (`tests/femm+windows`), or
  `tests/base` for none. `base` is always wanted; every part a posted part hands ids to is wanted too
  (`platformparts.derived`). A new tool is a new marker and nothing else.
- **A run** is one execution of one part's tests at one sha; its record is `run-<sha>-<part>-<req>.json.gz`
  (its `platform` key holds the part). An incremental part is its base part plus the re-run ids.
- **Admission** is computed from parts and never stored (`lab_commons.dev.pushgate`): a lane and the
  integration branch need no part; the trunk needs `tests/base` and every part a part hands to, each a PASS
  at scope `full` -- every derived part green. An unreadable forge makes the trunk wait.
- **One reader.** The integrator, issue readiness and admission all read parts through
  `lab_commons.dev.platformparts.standing`.
- An INCONCLUSIVE run is no part and posts nothing. Which ids a part runs is its need-set over the repo's
  `[tool.lab_commons.tests] resources` ([HPC clusters](hpc.md#parts-by-need-set)).

## Producing parts: `forge serve`

`python -m lab_commons.dev.forge serve` is the one call a crontab or harness makes on a producer host. It
takes no mode: EVERY HOST SERVES EVERY CANDIDATE CLASS from one queue ([scheduling](#scheduling)). The rank
decides ORDER and the admission decides FIT; nothing is reserved, lent or preempted (user ruling 2026-10-14).
Each tick it:

1. flushes the status outbox;
2. fetches origin and builds the queue of every derived part ([scheduling](#scheduling));
3. claims in rank order WHILE JOBS ADMIT ([admission](#admission)), posting `pending` for each;
4. runs every claimed local part at once, one thread each (streamed, each claim renewed every third of the
   lease), or advances a cluster run one step ([HPC clusters](hpc.md#runs-on-the-cluster));
5. posts the part with its record attached, and edits its host card;
6. on every host, keeps one forge issue per integration row and prompts the integrator when it writes one ([integration alarm](#alarms)).

- `forge tick` is the same claim step without producing (`--dry-run` to preview).
- **`--lock [PATH]`: one serve per host.** A second serve on a held lock exits 0 and says so. A bare
  `--lock` is `%LOCALAPPDATA%/lab-forge/serve.lock` on Windows, `~/.cache/lab-forge/serve.lock` elsewhere.
- **A Windows workstation serves from ONE Scheduled Task**, `lab-forge-serve` (every 5 min, IgnoreNew, as
  you, only while logged on, hidden), written by [the workstation deploy](#deploy-a-windows-workstation). Its
  action is the checkout's `pythonw.exe -m lab_commons.dev.workstation serve`, so NO console window opens:
  each child starts with `CREATE_NO_WINDOW` and every descendant inherits that windowless console. Output
  goes to `%LOCALAPPDATA%/lab-forge/serve.log` (rotated to `serve.log.1` at 4 MiB). Under the one serve
  lock it runs `forge serve` in each `[serve] repos` checkout in turn. **To stop it**, disable the Task --
  `schtasks /Change /TN lab-forge-serve /DISABLE` -- then stop a running serve with
  `python -m lab_commons.dev.stoprun --pid <pid>`: its producers stop first and its claim is released as
  `error: stopped`.
- **The producer argv is declared ONCE**, never typed: `[tool.lab_commons.tests] produce`, the argv after the
  tree's interpreter, carrying `{part}` (`["-m", "lab_commons.dev.verify", "--part", "{part}"]`), read AT THE
  CLAIMED SHA by `platformparts.producer_argv` with the claimed part filled in. It runs exactly that part's
  tests (`verify --part` selects them with one `-m`, `needsets.selecting`) and posts that part. A sha that
  declares no producer, or one never told its part, is not claimed, and the refusal names the key.
- **A local part is judged in a tree at the claimed sha** (`lab_commons.dev.shatree`), as a cluster run is:
  `<main checkout>/.claude/worktrees/forge-<sha12>`, detached at the sha, with its submodules and its own
  `.venv` (`-m lab_commons.dev.dep --bootstrap <tree>`). The declared argv runs there with that tree's
  interpreter, and the tree is removed once the run ends. The serving checkout's HEAD decides nothing about
  what is judged. A tree that cannot be built spawns nothing; the claim is released naming the step.
- **Serve cleans its own storage every tick** (`lab_commons.dev.retention` runs what `lab_commons.dev.retentionplan`
  decides; no cron line of its own). Files are the binding HPC resource, so the rules follow what each thing is
  FOR. One function says what is IN FLIGHT (`retentionplan.in_flight`): a sha a live run file names, a tree a
  queued or running Slurm job of the account works in (`squeue --me -o %Z` at or under `trees/<sha>`), or a sha
  whose run state, tree or `.lab-ci` stream directory was touched within `min_age_hours` (being built, or a round
  ended and not yet gathered). "No record yet" is NOT in flight: a superseded or released run is never gathered.
  A tree is kept only while its sha is
  in flight (`tree-not-in-flight`); an unrecorded run's round streams are packed into ONE file
  `runs/<sha>/streams/<tag>.txt` first, where the carry reads them (`hpc.records.stream_sources`), and a re-run re-adds the tree from the bare cache.
  An env, native build or cargo target is kept while an in-flight run or its repo's newest recorded run names it
  in `builds`; an unreadable reference keeps them all, an unreadable queue keeps every tree. A finished run's
  STATE goes when no origin branch tip can carry from it; finished `~/slurm-*.out` and oversized
  `~/.cache/lab-forge-*.log` (rotated) go too. On a workstation it removes the stale `forge-*` trees of the
  serving checkout. `git worktree prune` and `uv cache prune` follow a pass that deleted something; envs hardlink
  from the shared uv cache (`UV_LINK_MODE=hardlink`). Every deletion is one JSON line (path, bytes, files, rule).
  The file budget is the account's quota, the same reading admission uses as the `files` supply: at `pressure`
  of the block or file quota the kept carry-source runs also go, oldest first (most files first when files
  bind), down to `target`, and a `storage` alarm is raised if still over. The policy is the kit defaults,
  overridden per key by the machine file's `[retention]` table (an unknown or retired key is refused). Preview:
  `python -m lab_commons.dev.retention [--cluster]` is a DRY RUN: one line per path, then per rule paths, MB and
  files, and usage now -> after for bytes and FILES; `--apply` deletes.
- **An outdated kit refuses, never reads empty.** Every `[tool.lab_commons.<table>]` a judged commit declares
  must be one this lab-commons knows (`lab_commons.hpc.declared.KNOWN_TABLES`); an unknown table is refused
  with the remedy -- update the serving checkout -- instead of being read as an absent, empty table. The
  other way round, a RETIRED table (`lab_commons.hpc.retired`) is refused naming its replacement: the
  declaration is older than the kit ([migrating a repo](migrate.md#migrating-a-repo-to-need-set-parts)).
- **The HOST refreshes a served repo before its forge runs; a repo never updates itself** (incident 2026-10-13:
  a repo venv whose old `forge serve` exited 2 every tick could never run the code that would update it). A
  workstation's `workstation serve` fast-forwards lab-commons and then each `[serve]` repo to its upstream and
  syncs its venv when `pyproject.toml` or `uv.lock` changed (`lab_commons.dev.workstation.refresh`); a cluster
  account's cron line runs `python -m lab_commons.hpc tick <repo>` from the lab-commons checkout, which checks
  out both at their deployed refs and rebuilds the venv where its inputs or the kit's HEAD moved
  (`lab_commons.hpc.tick`). A repo whose refresh fails -- dirty, diverged, a sync that exits non-zero
  -- is released for that tick with its reason in the serve log, and the other repos are still served. The
  ref is the integration branch, not the trunk: a kit following the trunk would refuse the integration commit
  that adds a table, and that commit could then never reach the trunk.
- **The producer exit contract** (`lab_commons.dev.producer.ProducerExit`): `0` PASS, `1` FAIL, `2` refused
  argv, `3` INCONCLUSIVE (claim released `error`, not re-claimed), `4` UNREACHABLE (released, open again next
  tick); anything else is a crash. A consumer runner maps its own verdicts onto these codes.
- **A full tier runs only inside this producer.** Anywhere else it refuses and names the remedy: push.

### Deploy a Windows workstation

The counterpart of the cluster's `python -m lab_commons.hpc deploy`, run once per box, as the user who serves:

```
uv run --no-project --with "lab-commons @ git+<forge>/lab-commons.git@integrate/main" -- python -m lab_commons.dev.workstation deploy --forge <forge> --repos lab-commons,<repo>,... --capabilities dev_checkout,node,jmag:4 --dry-run
```

**The one manual step** comes first: store your own git credential for the forge (`git clone <forge>/lab-commons.git`
anywhere and sign in, or `python -m lab_commons.dev.forge auth login`). The deploy only asks `git ls-remote` with
prompting off, so it never reads or prints the credential, and with none stored it refuses naming this step.

Read the `--dry-run` output (every action, plus the machine-file diff), then run it again without `--dry-run`.
A second run changes nothing. In order, it:

1. probes for `uv` and `git`, `node` when the `node` capability is declared, and JMAG Designer's
   `designer.Application` and `scheduler.JobApplication` COM classes when `jmag` is. Everything missing is
   refused together, each item with its remedy;
2. clones each repo into `--root` (default `~/src`) at `--ref` (default `integrate/main`, the branch a serving kit
   follows), or fast-forwards an existing clean checkout. A dirty checkout is refused;
3. bootstraps each `.venv` (`-m lab_commons.dev.dep --bootstrap`) where it is missing or the checkout moved, and
   installs each repo's hooks where they are not live;
4. merges `[capabilities.<name>]` (`jmag:4` is `seats = 4`) and `[serve] repos, root` into
   `~/.config/lab-commons/config.toml`. Every other table, key and comment is kept;
5. writes the one `lab-forge-serve` Task from its XML definition, and only when the installed one reads back
   different -- so a re-run replaces an older `cmd /c` Task.

A workstation declares no `[deploy]`: nothing moves its checkouts between deploys except the user.

## Claims

- A claim is a `pending` status: `claim machine=<m> login=<forge login> until=<UTC> hpc=<cluster>/<account>|-`.
  The owner is machine + login + hpc, so two login hosts of one account are two claimants.
- A status post is not compare-and-swap: after posting, the claimant re-reads and the earliest live claim
  (lowest status id) holds; every other claimant stands down.
- `until` is the forge's clock plus the lease. Only the owner renews; a lapsed claim is retaken by any host
  that admits the part.
- **Progress travels on the claim**: the owner re-posts ` -- building`, ` -- queued 3/93`,
  ` -- running 40/93 done 12/93`, ` -- publishing`, cut to the forge's 140 characters.
- **A part under test is never superseded** (user ruling 2026-10-13). When a ref moves on, its in-flight
  run finishes and posts on its own sha; the newer pushes queue behind it and are tested at the next tip.
- **Carry what no change can reach** (`lab_commons.dev.forgecarry`, `lab_commons.dev.footprint`). Each test
  file's FOOTPRINT is derived at the judged sha: itself, its conftest/`__init__` chain, its transitive in-repo
  imports (candidates, so an added shadow counts), `pyproject.toml`/`uv.lock`, the declared `everywhere`
  globs -- and EVERYTHING when a module in it reads the repo by path (`__file__`, a repo-path literal,
  `subprocess`, `import_module`, ...) without a declared `reads` entry:
  `[tool.lab_commons.carry] everywhere = ["rust/**"]`, `[tool.lab_commons.carry.reads] "tests/x.py" = ["docs/**"]`.
  A test's outcome at A stands at a descendant B when no path in `git diff --no-renames A B` is in its footprint.
  - PER OUTCOME on a cluster run: B's run takes every such outcome its 3 nearest ancestor runs OF THE SAME PART AND ENV
    hold -- records, folded rounds, and the streams a superseded run's last round left -- and submits only the
    rest. The record's `carried` maps each id to the sha it RAN at; the part reads
    `scope=full ran=<run here> ... kept=<sha12>:<n>`, never counting a carried outcome as run.
  - PER PART: every test file at A carries and no test file is added -- the run finishes instead of being
    superseded and its part is also posted on the tip as `... carried from <sha12>: every outcome carried by footprint`.
    No ancestry, a malformed declaration, or a tip already settled: no carry.

## Scheduling

One work queue, derived from git and the forge every tick and never stored. Each candidate is a part a ref's
newest commit lacks, or a request issue.

- **Candidates** (`forgeschedule.candidates`), the same on every host: the integration branch
  (`integration`), every open PR into it (`pr`), every other origin branch the ONE CLASS RULE names
  (`classes_by_ref`, ordered, first match: `feat/*` and `fix/*` are `feature`, `lane/*` is `branch` by
  default; a branch no pattern matches is not served), and every open issue labelled `forge:request`
  (`request`: a body naming `producer = "<name>"` and `sha = "<40-hex>"`; the producer is declared at that
  sha under `[tool.lab_commons.requests.<name>]` with `argv`, its need-set `needs` and its size `cpu`,
  `mem_gb`, `wall_h` (an unsized row is refused), admitted like a part and claimed on context `request/<n>`
  -- `lab_commons.dev.forgerequest`). Publish one with `forge request <producer> --sha <sha>`, which refuses
  a sha origin does not serve. A host runs a request off origin's integration
  branch and trunk only for a login its machine file lists in `[requests] authors`; it waits, named, while a
  git source of its pyproject or submodules is unreachable here, and is told once on its issue after
  `request_unadmitted_hours`. A success is labelled `request:done` with its record path and sha256s, and the
  requester closes it. A ref's tip is one candidate per
  part it needs (`base`, and every part its posted parts hand to). The same rule names the integrator's
  children ([the integrator](integrator.md)).
- **Value** is `base[class] + boost + aging_rate * wait_hours`; a claimer takes the highest
  `weight[repo] * value / expected_cost` (weighted shortest job first). Aging grows without bound, so no
  class starves forever.
- **Cost** is the repo's last measured run (`lab_commons.compute.learned`), in core-hours on a cluster and
  wall-hours on a box; unmeasured work costs `prior_cost_h`.
- **Priority is a forge label** on the PR or issue: `priority:user` adds the declared boost, `priority:<n>`
  adds `n`.
- **Budgets.** A cluster charges each run's core-hours to its ref; a ref at its class's `daily_budget_core_h`
  is not claimed. A box meters no core-hours.
- **Admission** decides FIT; rank only decides ORDER ([admission](#admission)).
- **Starvation.** A candidate waiting past its class's `starve_after_hours` raises a `starved` alarm naming
  it, its wait and its blocking reason -- for a job that does not fit, the resources it lacks.

The numbers are data, `[tool.lab_commons.schedule]` over the family default
(`lab_commons.compute.model.Schedule`), overridden key by key -- except `classes_by_ref`, an ordered rule a
declaration replaces whole. Every class the rule names must be valued in `classes`:

```toml
[tool.lab_commons.schedule]
classes = {integration = 100, pr = 60, feature = 45, branch = 30, request = 20}
aging_rate = 10                                    # value per hour waited
starve_after_hours = {integration = 6, pr = 12, feature = 18, branch = 24, request = 48}
daily_budget_core_h = {}                           # class -> core-hours one ref may use per 24 h
boosts = {"priority:user" = 1000}                  # label -> value; `priority:<n>` adds n
classes_by_ref = {"feat/*" = "feature", "fix/*" = "feature", "lane/*" = "branch"}  # ordered, first match
request_label = "forge:request"
prior_cost_h = 4.0
```

### Admission

A tick walks the ranked queue and claims each candidate that ADMITS (`compute.admission.admit`): its needs are
present here and its demand fits `supply - running`. A job that does not fit is skipped and a smaller,
lower-ranked one is still claimed, so several parts run on one host at once.

- **Demand** is what the part's last run measured (`compute.learned`, keyed by part). A box part is admitted at
  exactly what it then DECLARES to the box (`compute.learned.box_demand`: the cores it kept busy and its peak
  memory with headroom; unmeasured, the D5 prior `compute.learned.part_prior` -- the median of this host's
  measured parts, else of every host's forge records for its need-set, else the per-task floor, never the whole
  box -- the last two are ONE worker's peak, so the part declares `PART_WIDTH` workers' cores and that many
  times the peak; past the box's memory the cores narrow in proportion; one seat of each tool it needs), and
  its producer runs in the box at that claim -- its pytest `-n` IS the declared cores (the box's
  `LAB_COMMONS_BOX_CPU`, `dev.verifybox.claimed_width`) -- holding against the
  capacity it was sized by (`box run --capacity`; [box resources](box-resources.md)). A cluster part asks what its last Slurm run measured.
- **Supply**: a cluster account's standing (every grant, cpu and memory, QOS submissions); on a box, what its
  ONE ledger can still admit (`compute.probe.box`): its capacity after the `[reserve]` margins (`cpu_margin`,
  default 1 core; `mem_margin`, default 0.25 of its memory) less every claim on it -- each producer serve runs
  and each interactive `verify` alike.
- **Running**: each cluster run in flight here at its learned demand, and each part this tick already claimed.
- **Two parts of one sha** are never claimed by one box in one tick: each is judged in its sha's tree.
- A job that does not fit waits `not admitted: lacking <resource>`; when every live host serving it says so,
  `forge queue` shows `no host admits it -- <host> lacking <resource>; ...`.

A host serving several repos weighs them in its machine file: `[schedule] weights = {"owner/name" = 2.0}`
(absent = 1); `[schedule] tick_minutes` (default 5) is what its card is judged stale against.
`[capabilities.<name>]` declares a resource it has beyond its OS (`seats` = its concurrency, the one number
no probe reads); a checked tool is present only where its check passes, and the card shows each verdict with
its evidence ([HPC clusters](hpc.md#parts-by-need-set)).

## The queue

```
python -m lab_commons.dev.forge queue [--json]
```

The one status command, from the forge alone, on any machine with a forge credential. It fetches origin and
prints the queue (class, value, cost, score, wait, blocking reason), every run in flight with its owner and
progress, every host card (stale flagged), every starved candidate, and every undeclared origin branch idle past its grace (`deletable`, `delete` or `stale`;
see [pruning origin](branch-set.md#pruning-origin)). It posts nothing.

- **Blocking reasons**: `no host serves it`, `no host provides <resource>` (no live card has every resource
  the part needs), `over budget: <ref> used X of Y core-h in 24 h`,
  `not admitted: lacking <resource>`, `no host admits it -- <host> lacking <resource>; ...`,
  `the tree of <sha12> is producing another part here`, `no host can produce it: <undeclared key>`.
- **Host cards** (`forgehosts`): each serving host edits one comment on the ONE `forge hosts` issue: who it
  is, its OS, its `supply` (what the tick admitted against), cluster facts (partitions, quota, QOS), its
  last tick, what it holds, what else `running` on it (each box ledger claim), and why each candidate it saw
  waits. A card key this version does not declare is not read. A card older than three of its own ticks is stale. The issue is the OLDEST carrying
  the hidden `forge-hosts` marker (or the title), read off every page in every state; a failed lookup, or a
  listing showing fewer open issues than the repository counts, refuses with an ALARM line and opens nothing.
- **Issue hygiene** (`forge tidy [--dry-run]`, run by `forge serve` on every host every tick): the rules and
  their defaults are in [issues](issues.md#issues-never-rot). It says so in ONE comment on the hosts issue.
- `compute.model.rank` is the one pure ordering rule; an optimiser replaces it without touching I/O.

## Alarms

`forgealarm` writes one JSON line `{"event": "lab_commons.forge.alarm", "kind", "repo", "subject", "body",
"delivered", "repeat"}` to stderr for: `auth` (401/403 or no credential), `lease` (a lease lost or not
renewable, orphaned jobs), `run` (a cluster run that cannot advance), `idle` (an account idle with work
pending), `starved`, and `integration` -- not a failure but a PROMPT: on EVERY host each tick derives the
integration queue and raises one alarm per row that asks for action (a READY lane, a PROMOTE-able tip, a
BLOCKED red to route), keyed by state, branch and tip, so a new row is delivered at once
([the integrator](integrator.md#waking-the-integrator)). The same host raises origin's branch hygiene:
`pruned` (the merged branches it deleted, or a prune that failed) and `stale-branch` (unmerged branches idle
past the grace, never deleted; see [pruning origin](branch-set.md#pruning-origin)). The machine file's
`[alerts]` table (telegram, email, webhook) delivers them; one `(kind, repo[, about])` is delivered at most
once per `[alerts] repeat_hours` (absent: 6) -- the receiver's decision, so it lives in the receiver's machine file.

## Records and the outbox

- **Statuses wait in an outbox** (`output/forge/outbox/` of the main checkout) until the commit is on origin.
  `python -m lab_commons.dev.forge publish` posts what is reachable; `verify` and every tick flush it too.
- **Run records are attachments** of one closed issue titled `run records`, never refs.
  `python -m lab_commons.dev.forge records list|prune [--keep-trunk N] [--dry-run]`; prune keeps every origin
  tip and the newest N trunk commits.
- `python -m lab_commons.dev.platformparts post <run-record>` turns a record into its part.
- `python -m lab_commons.dev.forge route <record>` files the record's reds as `area:<name>` issues
  ([issues](issues.md#reds-are-area-issues)). `[tool.lab_commons.forge.owners]` maps an area name or a
  branch glob to gitea usernames (`jmag = ["alice"]`, `"lane/*" = ["bob"]`); each matching owner is
  @-mentioned in a `cc` line closing the issue body. No table, no mentions; a malformed name is refused.
- A run's declared outputs travel separately, through [the artefact store](artefacts.md).

## Issues and pull requests: the door

Agents read and write the forge only through `python -m lab_commons.dev.forge` (`FORGE-THROUGH-THE-DOOR`);
no `gh` or `tea` binary is needed.

- Verbs: `issue list|view|create|comment|close|claim|status|comments`, `issue comments-since ISO8601`,
  `pr create|view`, `status post|list`. Every verb takes `--json` and returns the same shape on either forge.
- The backend is read off `origin`: `github.com` is GitHub REST, any other host is Gitea (`<host>/api/v1`).
- When `HARNESS_MACHINE` and `HARNESS_AGENT` are set, every created body opens with
  `[<machine> · <agent> · <branch>]`, so a write says which agent made it.
- Every call retries three times and then reports. A create whose answer was lost is read back before a retry,
  so a retry never makes a twin.

## Credentials

One command per forge host, run from a checkout whose `origin` is on it (or pass `--host`):

```
python -m lab_commons.dev.forge auth login      # prompts for the token, input hidden
python -m lab_commons.dev.forge auth status     # where the token comes from, and who it is
python -m lab_commons.dev.forge auth check      # can it do what a forge serve tick does (--url <repo url>)
```

- `login` checks the token against the forge and stores it with `git credential approve` only if accepted.
  The same credential then serves `git push`/`fetch` over https and the forge verbs. No environment variable
  is read, nothing is written into a repo, and only a hash prefix is ever printed.
- **Gitea**: User Settings -> Applications -> Generate Token, scopes `write:issue`, `write:repository`,
  `read:user`. **GitHub**: a fine-grained token with Issues, Pull requests and Contents read/write, or let Git
  Credential Manager's OAuth store it on the first push.
- Rotate by running `auth login` again; a revoked token shows as a failing `auth status`.

## Protecting `main` on the server

Configuration applied through the forge's API or web UI; enabling it is the human's decision.

- **Push whitelist**: only the integrator's accounts may update `main` (the client side: SESSION-HISTORY-ONLY-GROWS). A consumer's protection script applies
  it from a declared constant, so a new machine's account is added in code, not in the UI.
- **Required status check**: `tests/base` at least; parts are derived, so a required context per need-set
  goes stale when a marker changes. Enable it only once real parts exist on `main`'s tip; a required context
  nothing publishes blocks `main` for everyone. `integrate promote` already requires every derived part.
- The client side of the same rule is `integrate promote`, which moves `main` only by fast-forward to a fully green
  integration tip ([the integrator](integrator.md#promoting-the-trunk)).
