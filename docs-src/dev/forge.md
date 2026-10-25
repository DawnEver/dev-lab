# The forge

The forge (a self-hosted Gitea, or GitHub) is where every verdict lives. A pushed sha that lacks a
`tests/<part>` status is work; a `forge serve` host claims it, runs the suite once and posts the result.
You push, then read `python -m dev_lab.dev.forge queue` or `forge status list <sha>`. You never run a full
suite to learn whether a sha is green, and you never wait for one to push.

## Parts

- **A part** is one NEED-SET's result for one sha, posted as the commit status `tests/<part>`:
  its state is `forgestatus.state_for` of the part's `lab_commons.outcomes.Conclusion` -- `success` is
  PASS, `failure` is FAIL, `error` (INCONCLUSIVE) is never a settled part -- and `pending` is a claim. The
  record each status is read into is `forgestatus.CommitStatus`. The description is
  `scope=<full|incremental> ran=<n> hands=<part>:<n>,...`; `target_url` links the run record.
- **Parts are derived, never declared** ([parts by need-set](hpc.md#parts-by-need-set)). A test marks the
  resources it needs; its part is that set, named sorted and `+`-joined (`tests/femm+windows`), or
  `tests/base` for none. `base` is always wanted; every part a posted part hands ids to is wanted too
  (`platformparts.derived`). A new tool is a new marker and nothing else.
- **A run** is one execution of one part's tests at one sha; its record is `run-<sha>-<part>-<req>.json.gz`
  (its `platform` key holds the part). An incremental part is its base part plus the re-run ids.
- **Admission** is computed from parts and never stored (`dev_lab.dev.pushgate`): a lane and the
  integration branch need no part; the trunk needs `tests/base` and every part a part hands to, each a PASS
  at scope `full` -- every derived part green. An unreadable forge makes the trunk wait.
- **One reader.** The integration tick, issue readiness and admission all read parts through
  `dev_lab.dev.platformparts.standing`, which concludes PASS, FAIL or INCONCLUSIVE (unsettled).
- An INCONCLUSIVE run is no part and posts nothing. Which ids a part runs is its need-set over the repo's
  `[tool.lab_commons.tests] resources` ([HPC clusters](hpc.md#parts-by-need-set)).

## Producing parts: `forge serve`

`python -m dev_lab.dev.forge serve` is the one call a crontab or harness makes on a producer host. It
takes no mode: EVERY HOST SERVES EVERY CANDIDATE CLASS from one queue ([scheduling](#scheduling)). The rank
decides ORDER and the admission decides FIT; nothing is reserved, lent or preempted (user ruling 2026-10-14).
Each tick it:

1. flushes the status outbox;
2. fetches origin and builds the queue of every derived part ([scheduling](#scheduling));
3. claims in rank order WHILE JOBS ADMIT ([admission](#admission)), posting `pending` for each;
4. runs every claimed local part at once, one thread each (streamed, each claim renewed every third of the
   lease), or advances a cluster run one step ([HPC clusters](hpc.md#runs-on-the-cluster));
5. posts the part with its record attached, and edits its host card;
6. ON THE ONE POLLER of the repo ([one poller per repo](#one-poller-per-repo)): closes landed PRs, prunes
   merged branches and old records, tidies the issues, raises starved parts, keeps one forge issue per
   integration row (prompting the session whose row it is when it writes one, [integration alarm](#alarms)),
   runs the advisory review and the relock.

### One poller per repo

Measured 2026-10-24 on the gitea host (2 cores): 9425 API requests in ten minutes, 97% from two Ada login
nodes, gitea at 135% CPU -- five accounts each ran `hpchost tick` for seven repos every five minutes, and every
tick re-derived the same repo-wide answers. So the repo-wide poll (step 6) runs on ONE host per repo:

- **The lease is a comment on the hosts issue** (`forgepoller`, marker `poller`): `holder: <card host>` and
  `until: <forge time>`, judged on the FORGE's clock. Accounts on a cluster share no writable file, so the
  forge is the one place every host can read.
- A live lease held by another host: this host claims, produces, advances its runs and publishes its card,
  and polls nothing. Its own live lease: renewed, no read-back. None or expired: written, read back, and the
  host polls only if the read-back names it; racing creators keep the OLDEST lease comment and each deletes
  its own younger one. A lease lives three tick periods (`POLL_LEASE_TICKS`), so a dead holder is replaced
  within fifteen minutes at the default `tick_minutes = 5`.
- A race both hosts win costs one duplicate poll, never a wrong answer: every polled step was already idempotent.
- `[serve] poller: <host>` in the serve log names the holder each tick.

What every host still reads, kept small:

- **Issues incrementally**: a `client_for` client keeps every issue in `issues-<owner>-<repo>.json` in the
  outbox and asks only `since=` the forge's clock at its last read (less two minutes); a cold cache reads in
  full once, and an issue the tidy deletes is forgotten by it (`forgepulls.issues`).
- **Statuses of unsettled heads only**: a commit whose every derived part has a settled latest status never
  changes, so its history is kept in `settled-<owner>-<repo>.json` and never asked again
  (`forgesettled`); a claim still reads afresh, so the cache can cost a refused claim, never a duplicate.
- **Every request names its sender**: `User-Agent: dev-lab (<login>@<machine>; <owner>/<repo>)`.

- `forge tick` is the same claim step without producing (`--dry-run` to preview).
- **`--lock [PATH]`: one serve per host.** A second serve on a held lock exits 0 and says so. A bare
  `--lock` is `%LOCALAPPDATA%/lab-forge/serve.lock` on Windows, `<home>/.cache/lab-forge/serve.lock` elsewhere.
- **A Windows workstation serves from ONE Scheduled Task**, `lab-forge-serve` (every 5 min, IgnoreNew, as
  you, only while logged on, hidden), written by [the workstation deploy](#deploy-a-windows-workstation). Its
  action is the checkout's `pythonw.exe -m dev_lab.dev.workstation serve`, so NO console window opens:
  each child starts with `CREATE_NO_WINDOW` and every descendant inherits that windowless console. Output
  goes to `%LOCALAPPDATA%/lab-forge/serve.log` (rotated to `serve.log.1` at 4 MiB). Under the one serve
  lock it runs `forge serve` in each `[serve] repos` checkout in turn. **To stop it**, disable the Task --
  `schtasks /Change /TN lab-forge-serve /DISABLE` -- then stop a running serve with
  `python -m dev_lab.dev.stoprun --pid <pid>`: its producers stop first and its claim is released as
  `error: stopped`.
- **The producer argv is declared ONCE**, never typed: `[tool.lab_commons.tests] produce`, the argv after the
  tree's interpreter, carrying `{part}` (`["-m", "dev_lab.dev.verify", "--part", "{part}"]`), read AT THE
  CLAIMED SHA by `platformparts.producer_argv` with the claimed part filled in. It runs exactly that part's
  tests (`verify --part` selects them with one `-m`, `needsets.selecting`) and posts that part. A sha that
  declares no producer, or one never told its part, is not claimed, and the refusal names the key.
- **A local part is judged in a tree at the claimed sha** (`dev_lab.dev.shatree`), as a cluster run is:
  `<main checkout>/.claude/worktrees/forge-<sha12>`, detached at the sha, with its submodules and its own
  `.venv` (`-m dev_lab.dev.dep --bootstrap <tree>`). The declared argv runs there with that tree's
  interpreter, and the tree is removed once the run ends. The serving checkout's HEAD decides nothing about
  what is judged. A tree that cannot be built spawns nothing; the claim is released naming the step.
- **Serve cleans its own storage every tick** (`dev_lab.dev.retention` runs what `dev_lab.dev.retentionplan`
  decides; no cron line of its own). Files are the binding HPC resource, so the rules follow what each thing is
  FOR. One function says what is IN FLIGHT (`retentionplan.in_flight`): a sha a live run file names, a tree a
  queued or running Slurm job of the account works in (`squeue --me -o %Z` at or under `trees/<sha>`), or a sha
  whose run state, tree or `.lab-ci` round stream was touched within `min_age_hours` (being built, or a round
  ended and not yet gathered). "No record yet" is NOT in flight: a superseded or released run is never gathered.
  A round's items all append to ONE file `.lab-ci/<tag>.jsonl` (lines tagged `item`). A tree is kept only while
  its sha is in flight (`tree-not-in-flight`); an unrecorded run's round stream is kept as ONE file
  `runs/<sha>/streams.jsonl` first, where the carry reads it (`hpc.records.stream_sources`), and a re-run re-adds
  the tree from the bare cache. A run kept in the retired many-file shape is upgraded into it (`streams-upgraded`).
  An env, native build or cargo target is kept while an in-flight run or its repo's newest recorded run names it
  in `builds`; an unreadable reference keeps them all, an unreadable queue keeps every tree. A finished run's
  STATE goes when no origin branch tip can carry from it; finished `~/slurm-*.out` and oversized
  `<home>/.cache/lab-forge-<n>.log` (rotated) go too. On a workstation it removes the stale `forge-*` trees of the
  serving checkout. `git worktree prune` and `uv cache prune` follow a pass that deleted something; envs hardlink
  from the shared uv cache (`UV_LINK_MODE=hardlink`). Every deletion is one JSON line (path, bytes, files, rule).
  The file budget is the account's quota, the same reading admission uses as the `files` supply: at `pressure`
  of the block or file quota the kept carry-source runs also go, oldest first (most files first when files
  bind), down to `target`, and a `storage` alarm is raised if still over. The policy is the kit defaults,
  overridden per key by the machine file's `[retention]` table (an unknown or retired key is refused). Preview:
  `python -m dev_lab.dev.retention [--cluster]` is a DRY RUN: one line per path, then per rule paths, MB and
  files, and usage now -> after for bytes and FILES; `--apply` deletes.
- **An outdated kit refuses, never reads empty.** Every `[tool.lab_commons.<table>]` a judged commit declares
  must be one this lab-commons knows (`lab_commons.hpc.declared.KNOWN_TABLES`); an unknown table is refused
  with the remedy -- update the serving checkout -- instead of being read as an absent, empty table. The
  other way round, a RETIRED table (`lab_commons.hpc.retired`) is refused naming its replacement: the
  declaration is older than the kit ([migrating a repo](migrate.md#migrating-a-repo-to-need-set-parts)).
- **PIN + FRESHNESS (user ruling 2026-10-17).** Every repo commits `uv.lock`, and every install -- `dep
  --bootstrap`, a cluster's served venv, a workstation refresh -- is `uv sync --frozen` from the commit's lock:
  a commit's code and its exact dependencies are tested together and identical on every host, and the lock's
  hash keys the served venv. So a RUN judges its environment against the checkout's own lock and nothing
  else: `verify` refuses as STALE only when a git-installed package's commit differs from the one `uv.lock` at
  HEAD pins (`dev_lab.dev.lockpins`) -- never against a dependency's remote tip, which would leave every
  commit locked before its dependency moved without a producible part. The forge refuses (`dev_lab.dev.famtests.lockpin`, in the repo's own suite at the
  checked-out sha; no pre-push row reads the lock, user ruling 2026-10-24) a commit
  that commits no lock, or that holds a requirement below the newest (an upper bound, an exact
  pin, a git rev) with no reason on its line or the comment line above. A reasoned range is the only way to
  stay below latest. Every commit is judged on its pin alone (user ruling 2026-10-22): freshness is ONE party's job, the forge's --
  each serve tick relocks `origin/<integration>` itself through one `pr/relock-<dist>-<sha>` pull request
  (`dev_lab.dev.relock`), which merges like any other, and a lane takes it with `forge sync`. Every open PR head into integration
  carries a `lock/fresh` status (`dev_lab.dev.forgeheadgate`, once per head sha): `failure` reads
  ``stale uv.lock: run `<venv python> -m dev_lab.dev.dep --lock-upgrade [ROOT]`, then commit uv.lock (<moves>)``. By hand, one
  upgrades through the door `<venv python> -m dev_lab.dev.dep --lock-upgrade
  [ROOT]` (`uv lock --upgrade` under the same reasoned-hold rules, then a frozen sync of that checkout), then
  fixes, tests and commits. A
  resolution that cannot run (the network is down) refuses with its diagnosis; a deletion is never judged.
- **The HOST refreshes a served repo before its forge runs; a repo never updates itself** (incident 2026-10-13:
  a repo venv whose old `forge serve` exited 2 every tick could never run the code that would update it). A
  workstation's `workstation serve` fast-forwards dev-lab and then each `[serve]` repo to its upstream and
  syncs its venv when `pyproject.toml` or `uv.lock` changed (`dev_lab.dev.workstation.refresh`); a cluster
  account's cron line runs `python -m dev_lab.dev.hpchost tick <repo>` from the dev-lab checkout, which checks
  out both at their deployed refs and rebuilds the venv where its inputs or the kit's HEAD moved
  (`dev_lab.dev.hpchost.tick`). A repo whose refresh fails -- dirty, diverged, a sync that exits non-zero
  -- is released for that tick with its reason in the serve log, and the other repos are still served. The
  ref is the integration branch, not the trunk: a kit following the trunk would refuse the integration commit
  that adds a table, and that commit could then never reach the trunk.
- **The producer exit contract** (`dev_lab.dev.producer.ProducerExit`): `0` PASS, `1` FAIL, `2` refused
  argv, `3` INCONCLUSIVE (claim released `error`, not re-claimed), `4` UNREACHABLE (released, open again next
  tick); anything else is a crash. A consumer runner maps its own verdicts onto these codes.
  A box with no room for the producer is capacity, never a verdict: it exits `4`, so the claim goes back to
  claimable naming the holder; an exit-3 release already posted stays settled (it cannot tell no room from
  a run that wrote nothing), so such a head waits for its ref's next push or a human re-run.
- **A full tier runs only inside this producer.** Anywhere else it refuses and names the remedy: push.

### Deploy a Windows workstation

The counterpart of the cluster's `python -m dev_lab.dev.hpchost deploy`, run once per box, as the user who serves:

```
uv run --no-project --with "dev-lab @ git+<forge>/dev-lab.git@integrate/main" -- python -m dev_lab.dev.workstation deploy --forge <forge> --repos dev-lab,<repo>,... --capabilities workstation,jmag:4 --dry-run
```

**The one manual step** comes first: store your own git credential for the forge (`git clone <forge>/dev-lab.git`
anywhere and sign in, or `python -m dev_lab.dev.forge auth login`). The deploy only asks `git ls-remote` with
prompting off, so it never reads or prints the credential, and with none stored it refuses naming this step.

Read the `--dry-run` output (every action, plus the machine-file diff), then run it again without `--dry-run`.
A second run changes nothing. In order, it:

1. probes for `uv` and `git`, `node` when the `node` capability is declared, and JMAG Designer's
   `designer.Application` and `scheduler.JobApplication` COM classes when `jmag` is. Everything missing is
   refused together, each item with its remedy;
2. clones each repo into `--root` (default `~/src`) at `--ref` (default `integrate/main`, the branch a serving kit
   follows), or fast-forwards an existing clean checkout. A dirty checkout is refused;
3. bootstraps each `.venv` (`-m dev_lab.dev.dep --bootstrap`) where it is missing or the checkout moved, and
   installs each repo's hooks where they are not live;
4. merges `[capabilities.<name>]` (`jmag:4` is `seats = 4`) and `[serve] repos, root` into
   `~/.config/lab-commons/config.toml`. Every other table, key and comment is kept;
5. writes the one `lab-forge-serve` Task from its XML definition, and only when the installed one reads back
   different -- so a re-run replaces an older `cmd /c` Task.

A workstation declares no `[deploy]`: nothing moves its checkouts between deploys except the user.

**Which workstation serves is declared in ONE place**: the synced workstation registry `hosts.json`
(`{"hosts": [{"name", "computer", "roles": [...], ...}]}`), named per machine by
`[workstation] registry = "<path>"` in `~/.config/lab-commons/config.toml`. A host serves only when its entry
carries role `"forge"`. Its entry is the one whose `computer` equals `COMPUTERNAME` (case-insensitive), else the
one whose `name` does. Each `workstation serve` tick checks the role first:

- no `[workstation] registry` declared: refused by name, exit 2 -- a workstation never serves by omission;
- an entry without `"forge"`, or no entry: it claims nothing and refreshes nothing, logs
  `[serve] not a forge host (...)` naming the roles, releases any run a dead serve left journaled (the forge
  serve's own re-attach path, `forgeintent.reattach`), and exits 0;
- `"forge"` present: it serves as above.

`workstation deploy` refuses on a host without the role, naming the registry and the role to add. The cluster
serve (`lab_commons.hpc`) does not read the registry.

## Claims

- A claim is a `pending` status: `claim machine=<m> login=<forge login> until=<UTC> hpc=<cluster>/<account>|-`.
  The owner is machine + login + hpc, so two login hosts of one account are two claimants.
- A status post is not compare-and-swap: after posting, the claimant re-reads and the earliest live claim
  (lowest status id) holds; every other claimant stands down.
- `until` is the forge's clock plus the lease. Only the owner renews; a lapsed claim is retaken by any host
  that admits the part.
- **Progress travels on the claim**: the owner re-posts ` -- building`, ` -- queued 3/93`,
  ` -- running 40/93 done 12/93`, ` -- publishing`, cut to the forge's 140 characters.
- **NEWEST-HEAD-ONLY: a coalesced ref's run loses its pending tasks the tick its ref moves on, never a started one**
  (user ruling 2026-10-22, `dev_lab.dev.forgerun`). For a class in `Schedule.coalesce`, a run whose sha is no
  longer its ref's tip has every not-yet-started task withdrawn (`scancel --state=PENDING`); its started tasks run
  to the end under a ` -- draining` claim, the tip waits behind it, and the tip's run carries what they finished.
  Then it is released as superseded naming the tip, with one alarm. Only a deliberate stop (`hpc.run.cancel_run`)
  kills a started task. Only a run already
  `publishing` its gathered record finishes. A ref of any other class is tested at every pushed sha: its run
  finishes and posts on its own sha, and the newer pushes are tested after it.
- **Carry what no change can reach** (`dev_lab.dev.forgecarry`, `dev_lab.dev.footprint`). Each test
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
  - PER PART (a class tested at every sha): every test file at A carries and no test file is added -- the run
    finishes and its part is also posted on the tip as `... carried from <sha12>: docs-only`.
    No ancestry, a malformed declaration, or a tip already settled: no carry.
  - DOCS-ONLY-CARRIES (user ruling 2026-10-21; `forgecarry.docs_only`): a head PER PART-equivalent to the nearest
    tested or running head of its first-parent history -- memory written after the code commit -- is never claimed.
    Settled there: the verdict is posted on it `carried from <sha12>: docs-only`, no job. Running there: it waits
    `waiting behind <sha12> (docs-only: ...)`, that run is never superseded for it, and its result carries when it
    lands. An untested code head in between makes the diff reach a test, so the head runs. The PR review of such a
    head is carried the same way: the earlier head's review stands and no command runs.
  - DATA-ONLY WAITS (2026-10-22, `forgecarry.data_only`): a head whose diff holds no Python, no `ALWAYS` path and
    no `everywhere` glob but that a whole-tree read (`reads = ["*"]`) still reaches is not equivalent -- it WAITS
    while its source runs, then runs carrying every outcome its diff cannot reach, instead of running beside it
    and carrying nothing. Measured: motronics `a3b326d0a829` (docs(memory), 2026-10-20) ran beside its running
    parent with `carried 0`; 427 of 5124 test files there reach a memory path through declared `"*"` reads.

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
  -- `dev_lab.dev.forgerequest`). Publish one with `forge request <producer> --sha <sha>`, which refuses
  a sha origin does not serve or that commits no `uv.lock`. A host runs a request off origin's integration
  branch and trunk only for a login its machine file lists in `[requests] authors`; it waits, named, while a
  git source of its lock or submodules is unreachable here, and is told once on its issue after
  `request_unadmitted_hours`. A success is labelled `request:done` with its record path and sha256s, and the
  requester closes it. A ref's tip is one candidate per
  part it needs (`base`, and every part its posted parts hand to). The same rule names those
  children ([the integration branch](integration.md)).
- **Value** is `base[class] + boost + aging_rate * wait_hours`; a claimer takes the highest
  `weight[repo] * value / expected_cost` (weighted shortest job first). Aging grows without bound, so no
  class starves forever.
- **Order on a scarce host** (user ruling 2026-10-22, `compute.model.rank`): a host's `[priority]` first, then
  a candidate the user boosted, then the `served_first` classes strictly in their order (`integration`, then
  `pr`), then every other class by score. Within an `oldest_first` class (`pr`) the OLDEST sha goes first, not
  the cheapest -- G is the only Windows forge host, so a PR never waits behind a lane or a newer PR. A `pr` head
  is coalesced (`Schedule.coalesce`): one PR session holds at most one run per part in flight, and a child's
  coalescing reads only ITS OWN commits, never the integration run it branched from.
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
coalesce = ["integration", "feature", "pr"]       # one run per (ref, part) in flight; the tip waits behind it
served_first = ["integration", "pr"]              # served strictly before every other class, in this order
oldest_first = ["pr"]                             # ordered by age, not score
request_label = "forge:request"
prior_cost_h = 4.0
```

### Admission

A tick walks the ranked queue and claims each candidate that ADMITS (`compute.admission.admit`): its needs are
present here and its demand fits `supply - running`. A job that does not fit is skipped and a smaller,
lower-ranked one is still claimed, so several parts run on one host at once.

- **Demand** is what the part's last run measured (`compute.learned`, keyed by part). A box part is admitted at
  exactly what it then DECLARES to the box (`compute.learned.box_demand`: the cores it kept busy and its peak
  memory with headroom; unmeasured, its SELECTION `compute.learned.selection_gb` -- the arithmetic a verify
  selection reads too: one worker per id the commit's parts hand it, up to `PART_WIDTH`, each at the worst
  learned peak of the files its need-set's latest forge record ran (`part_files`) with headroom, never under
  the per-task floor, never the whole box; the width is `compute.learned.fit_width` -- narrowed to the box's
  FREE cores and the workers its FREE memory holds at that price, never under one; one seat of
  each tool it needs), and
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
python -m dev_lab.dev.forge queue [--json]
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
  the hidden `forge-hosts` marker (or the title), read off the issue cache in every state; a failed lookup, or a
  listing showing fewer open issues than the repository counts, refuses with an ALARM line and opens nothing.
- **Issue hygiene** (`forge tidy [--dry-run]`, run by `forge serve` on the repo's poller every tick): the rules and
  their defaults are in [issues](issues.md#issues-never-rot). It says so in ONE comment on the hosts issue.
- `compute.model.rank` is the one pure ordering rule; an optimiser replaces it without touching I/O.

### Watching a sha, and cancelling its stuck tasks

`python -m dev_lab.dev.forge watch <sha> [--deadline-minutes M]` only reads: it prints each `tests/<part>`
change until every part is final (exit 0 green, 1 red) or the deadline passes (exit 3).

`python -m dev_lab.dev.forge cancel-stuck <sha> [--factor N] [--bound-minutes M]`, run in the repo's checkout,
scancels only the full sha's `run-<sha12>-<part>` tasks that are busy (90 % CPU or more) with no new test line in
their stream for longer than `N x` the longest measured duration of the shard's tests (the learned `durations`
every host prices from). A shard holding an unmeasured test is floored at `M` minutes, named `unmeasured` in the
output. Every other task of the sha is listed as healthy; no other job is cancelled.

## Alarms

`forgealarm` writes one JSON line `{"event": "lab_commons.forge.alarm", "kind", "repo", "subject", "body",
"delivered", "repeat"}` to stderr for: `auth` (a credential `GET /user` still refuses after git's refresh, or none stored -- a 401/403 whose credential authenticates or refreshes is never an `auth` alarm; [why](#a-gitea-auth-refusal-is-an-expired-oauth-token-not-a-bad-credential)), `lease` (a lease lost or not
renewable, orphaned jobs), `run` (a cluster run that cannot advance), `idle` (an account idle with work
pending), `starved`, and `integration` -- not a failure but a PROMPT: on EVERY host each tick derives the
integration queue and raises one alarm per row that asks for action (a READY lane, a PROMOTE-able tip, a
BLOCKED red to route), keyed by state, branch and tip, so a new row is delivered at once
([the integration branch](integration.md#waking-the-steward)). The same host raises origin's branch hygiene:
`pruned` (the merged branches it deleted, or a prune that failed) and `stale-branch` (unmerged branches idle
past the grace, never deleted; see [pruning origin](branch-set.md#pruning-origin)). The machine file's
`[alerts]` table (telegram, email, webhook) delivers them; one `(kind, repo[, about])` is delivered at most
once per `[alerts] repeat_hours` (absent: 6) -- the receiver's decision, so it lives in the receiver's machine file.

## Records and the outbox

- **Statuses wait in an outbox** (`<main-checkout>/output/forge/outbox/`) until the commit is on origin.
  `python -m dev_lab.dev.forge publish` posts what is reachable; `verify` and every tick flush it too.
- **Run records are attachments** of one closed issue titled `run records`, never refs.
  `python -m dev_lab.dev.forge records list|prune [--keep-trunk N] [--dry-run]`; prune keeps every origin
  tip and the newest N trunk commits.
- `python -m dev_lab.dev.platformparts post <run-record>` turns a record into its part.
- `python -m dev_lab.dev.forge route <record>` files the record's reds as `area:<name>` issues
  ([issues](issues.md#reds-are-area-issues)). `[tool.lab_commons.forge.owners]` maps an area name or a
  branch glob to gitea usernames (`jmag = ["alice"]`, `"lane/*" = ["bob"]`); each matching owner is
  @-mentioned in a `cc` line closing the issue body. No table, no mentions; a malformed name is refused.
- A run's declared outputs travel separately, through [the artefact store](artefacts.md).

## Issues and pull requests: the door

Agents read and write the forge only through `python -m dev_lab.dev.forge` (`FORGE-THROUGH-THE-DOOR`);
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
python -m dev_lab.dev.forge auth login      # prompts for the token, input hidden
python -m dev_lab.dev.forge auth status     # where the token comes from, and who it is
python -m dev_lab.dev.forge auth check      # can it do what a forge serve tick does (--url <repo url>)
```

- `login` checks the token against the forge and stores it with `git credential approve` only if accepted.
  The same credential then serves `git push`/`fetch` over https and the forge verbs. No environment variable
  is read, nothing is written into a repo, and only a hash prefix is ever printed.
- **Gitea**: User Settings -> Applications -> Generate Token, scopes `write:issue`, `write:repository`,
  `read:user`. **GitHub**: a fine-grained token with Issues, Pull requests and Contents read/write, or let Git
  Credential Manager's OAuth store it on the first push.
- Rotate by running `auth login` again; a revoked token shows as a failing `auth status`.

### A gitea auth refusal is an expired OAuth token, not a bad credential

THE ONE EXPLANATION; every refusal remedy, alarm and rule that mentions a forge 401 points here.

- Measured 2026-10-21: on a Windows box `git credential fill` for the forge answers username `OAUTH_USER` --
  Git Credential Manager's OAuth store. Its ACCESS token EXPIRES. git sends it, the forge answers 401
  (`remote: Failed to authenticate user`), git `reject`s it, and the NEXT `fill` makes GCM spend its refresh
  token on a new one. That is the whole "every git network verb fails on attempt 1 and succeeds on attempt 2"
  -- not a flaky server, not a mystery transient. `netverb`'s retry is what lets git finish its own refresh.
- The forge API client does the same (`dev_lab.dev.forgecred.refresh_credential`): on a 401 that `GET /user`
  confirms it rejects the refused secret, fills again and retries the call once with the refreshed token.
- Only a refusal AFTER that refresh is permanent, and it does NOT ask for `auth login`: the account, its scopes
  or the forge refuse a credential that was just refreshed, so report the output. `auth login` is named only
  when the refresh leaves the store EMPTY -- a plain stored token has no refresh token, so the reject removes it.
- So the forge never needs a re-login on an OAuth box. Never run `auth login` because of one 401.

## Protecting `main` on the server

Configuration applied through the forge's API or web UI; enabling it is the human's decision.

- **Push whitelist**: only the steward's account may update `main` (the client side: SESSION-HISTORY-ONLY-GROWS). A consumer's protection script applies
  it from a declared constant, so a new machine's account is added in code, not in the UI.
- **Required status check**: `tests/base` at least; parts are derived, so a required context per need-set
  goes stale when a marker changes. Enable it only once real parts exist on `main`'s tip; a required context
  nothing publishes blocks `main` for everyone. `integrate promote` already requires every derived part.
- The client side of the same rule is `integrate promote`, which moves `main` only by fast-forward to a fully green
  integration tip ([the integration branch](integration.md#promoting-the-trunk)).
