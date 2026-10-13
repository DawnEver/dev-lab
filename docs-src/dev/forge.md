# The forge

The forge (a self-hosted Gitea, or GitHub) is where every verdict lives. A pushed sha that lacks a
`tests/<platform>` status is work; a `forge serve` host claims it, runs the suite once and posts the result.
You push, then read `python -m lab_commons.dev.forge queue` or `forge status list <sha>`. You never run a full
suite to learn whether a sha is green, and you never wait for one to push.

## Parts

- **A part** is one platform's result for one sha, posted as the commit status `tests/<platform>` (`linux`,
  `windows`, `macos`): `success` is PASS, `failure` is FAIL, `pending` is a claim. The description is
  `scope=<full|incremental> ran=<n> hands=<platform>:<n>,... nowhere=<n>`; `target_url` links the run record.
- **A run** is one execution of a test set on one platform at one sha; its record is
  `run-<sha>-<platform>-<req>.json.gz`. An incremental part is its base part plus the re-run ids.
- **Admission** is computed from parts and never stored (`lab_commons.dev.admission`): a lane and the
  integration branch need no part; the trunk needs every required part of HEAD a PASS at scope `full`. An
  unreadable forge makes the trunk wait.
- **One reader.** The integrator, issue readiness and admission all read parts through
  `lab_commons.dev.platformparts.standing`.
- An INCONCLUSIVE run is no part and posts nothing. Which ids each platform runs is the repo's
  `[tool.lab_commons.platforms]` and `[tool.lab_commons.capabilities]` tables
  ([HPC clusters](hpc.md#platform-parts)).

## Producing parts: `forge serve`

`python -m lab_commons.dev.forge serve --mode integrate|develop|quiet` is the one call a crontab or harness
makes on a producer host. Each tick it:

1. flushes the status outbox (`quiet` stops here);
2. fetches origin and builds the queue for its own platform ([scheduling](#scheduling));
3. claims the best feasible candidate by posting `pending`;
4. runs a claimed local part inline (streamed, its claim renewed every third of the lease), or advances a
   cluster run one step ([HPC clusters](hpc.md#runs-on-the-cluster));
5. posts the part with its record attached, and edits its host card.

- `--mode integrate` serves the integration branch, open PRs into it and opted-in branches; `--mode develop`
  serves the lanes. `forge tick` is the same claim step without producing (`--dry-run` to preview).
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
- **The producer argv is declared**, never typed: `[tool.lab_commons.parts] produce.<platform>.<full|incremental>`
  in the repo's `pyproject.toml`, read AT THE CLAIMED SHA by `platformparts.part_argv`. A part whose producer
  the sha does not declare is not claimed, and the refusal names the key.
- **A local part is judged in a tree at the claimed sha** (`lab_commons.dev.shatree`), as a cluster run is:
  `<main checkout>/.claude/worktrees/forge-<sha12>`, detached at the sha, with its submodules and its own
  `.venv` (`-m lab_commons.dev.dep --bootstrap <tree>`). The declared argv runs there with that tree's
  interpreter, and the tree is removed once the run ends. The serving checkout's HEAD decides nothing about
  what is judged. A tree that cannot be built spawns nothing; the claim is released naming the step.
- **An outdated kit refuses, never reads empty.** Every `[tool.lab_commons.<table>]` a judged commit declares
  must be one this lab-commons knows (`lab_commons.hpc.declared.KNOWN_TABLES`); an unknown table is refused
  with the remedy -- update the serving checkout -- instead of being read as an absent, empty table.
- **A deployed host keeps its own lab-commons current** (`lab_commons.dev.servekit`). On a host whose machine
  file declares `[deploy]`, every serve tick first fast-forwards the deployed lab-commons checkout to
  `origin/<its deployed ref>`. If HEAD moved, the tick reinstalls lab-commons into its own venv (the deploy's
  `overlay_argv`; skipped when the venv imports the checkout itself) and re-executes the serve, so this
  tick's claim runs the new code. A checkout that is dirty, off its ref, or diverged is refused: an alarm is
  raised, exit 1, nothing claimed. The ref is the integration branch, not the trunk: a kit following the
  trunk would refuse the integration commit that adds a table, and that commit could then never reach the
  trunk. A workstation declares no `[deploy]`, so its serving checkout (a human's) is never moved by a tick.
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
4. merges `[capabilities.<name>]` (`jmag:4` is `seats = 4`) and `[serve] repos, root, own_weight` (`--own-weight`,
   default 2) into `~/.config/lab-commons/config.toml`. Every other table, key and comment is kept;
5. writes the one `lab-forge-serve` Task from its XML definition, and only when the installed one reads back
   different -- so a re-run replaces an older `cmd /c` Task.

A workstation declares no `[deploy]`: nothing moves its checkouts between deploys except the user.

## Claims

- A claim is a `pending` status: `claim machine=<m> login=<forge login> until=<UTC> hpc=<cluster>/<account>|-`.
  The owner is machine + login + hpc, so two login hosts of one account are two claimants.
- A status post is not compare-and-swap: after posting, the claimant re-reads and the earliest live claim
  (lowest status id) holds; every other claimant stands down.
- `until` is the forge's clock plus the lease. Only the owner renews; a lapsed claim is retaken by anyone
  serving the platform.
- **Progress travels on the claim**: the owner re-posts ` -- building`, ` -- queued 3/93`,
  ` -- running 40/93 done 12/93`, ` -- publishing`, cut to the forge's 140 characters.
- **Supersede.** When a ref moves on, its in-flight run is cancelled and released `superseded by <sha12>`.
- **Carry, not supersede, across an inert diff** (`lab_commons.dev.forgecarry`). A repo declares the paths
  no test reads, `[tool.lab_commons.parts] inert = [".claude/memory/**", "docs-src/**", "*.md"]`
  (`fnmatch`, `*` crosses `/`). When the new tip descends from the run's sha and every path in
  `git diff --no-renames` matches, the run finishes; its part is posted on its own sha and on the tip as
  `scope=... carried from <sha12>: only inert paths changed`, which admission and promote read as the part
  it is. One non-inert path, no ancestry, nothing declared, or a tip already settled: no carry.

## Scheduling

One work queue, derived from git and the forge every tick and never stored. Each candidate is a part a ref's
newest commit lacks, or a request issue.

- **Candidates** (`forgeschedule.candidates`): in integrate mode the integration branch (`integration`), every
  open PR into it (`pr`), every opted-in branch (`branch`), every open issue labelled `forge:request`
  (`request`; platform from `platform = "<p>"` in the body, else linux). In develop mode, the lanes.
- **Value** is `base[class] + boost + aging_rate * wait_hours`; a claimer takes the highest
  `weight[repo] * value / expected_cost` (weighted shortest job first). Aging grows without bound, so no
  class starves forever.
- **Cost** is the repo's last measured run (`lab_commons.hpc.learned`), in core-hours on a cluster and
  wall-hours on a box; unmeasured work costs `prior_cost_h`.
- **Priority is a forge label** on the PR or issue: `priority:user` adds the declared boost, `priority:<n>`
  adds `n`.
- **Budgets.** A cluster charges each run's core-hours to its ref; a ref at its class's `daily_budget_core_h`
  is not claimed. A box meters no core-hours.
- **Feasibility.** A claimer considers its own platform only: a cluster needs one free core of its grant and
  one QOS submission; a box needs its CPU seat free.
- **Starvation.** A candidate waiting past its class's `starve_after_hours` raises a `starved` alarm naming
  it, its wait and its blocking reason.

The numbers are data, `[tool.lab_commons.schedule]` over the family default
(`lab_commons.dev.forgeschedule.Schedule`), overridden key by key:

```toml
[tool.lab_commons.schedule]
classes = {integration = 100, pr = 60, branch = 30, request = 20}
aging_rate = 10                                    # value per hour waited
starve_after_hours = {integration = 6, pr = 12, branch = 24, request = 48}
daily_budget_core_h = {}                           # class -> core-hours one ref may use per 24 h
boosts = {"priority:user" = 1000}                  # label -> value; `priority:<n>` adds n
branches = []                                      # opted-in child branches
request_label = "forge:request"
prior_cost_h = 4.0
```

A host serving several repos weighs them in its machine file: `[schedule] weights = {"owner/name" = 2.0}`
(absent = 1); `[schedule] tick_minutes` (default 5) is what its card is judged stale against.
`[serve] own_weight` (absent = 1) multiplies the value of candidates whose PR or request this host's own
forge login opened -- on this host only; `[capabilities.<name>]` declares what it provides
([HPC clusters](hpc.md#platform-parts)).

## The queue

```
python -m lab_commons.dev.forge queue [--json]
```

The one status command, from the forge alone, on any machine with a forge credential. It fetches origin and
prints the queue (class, value, cost, score, wait, blocking reason), every run in flight with its owner and
progress, every host card (stale flagged) and every starved candidate. It posts nothing.

- **Blocking reasons**: `no host serves <platform>`, `over budget: <ref> used X of Y core-h in 24 h`,
  `no headroom: ...`, `outranked by <candidate>`, `no host can produce it: <undeclared key>`.
- **Host cards** (`forgehosts`): each serving host edits one comment on the ONE `forge hosts` issue: who it
  is, its platform, headroom, cluster facts (partitions, quota, QOS), its last tick, what it holds and why each
  candidate it saw waits. A card older than three of its own ticks is stale. The issue is the OLDEST carrying
  the hidden `forge-hosts` marker (or the title), read off every page in every state; a failed lookup, or a
  listing showing fewer open issues than the repository counts, refuses with an ALARM line and opens nothing.
- **Issue hygiene** (`forge tidy [--dry-run]`, run by `forge integration`): removes what
  `[tool.lab_commons.forge.issue_hygiene]` declares finished. `host_duplicates` DELETES every machine-made hosts
  issue but the oldest (user ruling 2026-10-13; a human-written one is never touched, and a token without
  delete rights closes instead and says so); `green_areas` (an `area:*` issue with no `- [ ]` row) and
  `request_max_age_days` only CLOSE. It says so in ONE comment on the hosts issue; absent the table, it reads nothing.
- `forgeschedule.rank` is the one pure ordering rule; an optimiser replaces it without touching I/O.

## Alarms

`forgealarm` writes one JSON line `{"event": "lab_commons.forge.alarm", "kind", "repo", "subject", "body",
"delivered", "repeat"}` to stderr for: `auth` (401/403 or no credential), `lease` (a lease lost or not
renewable, orphaned jobs), `run` (a cluster run that cannot advance), `idle` (an account idle with work
pending) and `starved`. The machine file's `[alerts]` table (telegram, email, webhook) delivers them; one
`(kind, repo[, candidate])` is delivered at most once per 6 h.

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

- **Push whitelist**: only the integrator's accounts may update `main`. A consumer's protection script applies
  it from a declared constant, so a new machine's account is added in code, not in the UI.
- **Required status check**: one `tests/<platform>` context per platform the repo's parts run on. Enable it
  only once real parts exist on `main`'s tip; a required context nothing publishes blocks `main` for everyone.
- The client side of the same rule is `forge promote`, which moves `main` only by fast-forward to a fully green
  integration tip ([the integrator](integrator.md#promoting-the-trunk)).
