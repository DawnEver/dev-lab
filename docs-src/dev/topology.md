# Development architecture and topology

The one map of the family's development system: which repositories exist and how they depend, how a change
travels, which forges and identities carry it, which hosts do what, and how each piece is configured. Every
section states the shape and points at the page or module that owns the detail; nothing here restates a rule. The normative design this map serves is
[the family architecture](architecture.md).

The concrete instance -- host names, addresses, account logins, App ids, cluster names -- is never written in
this public repo. A family keeps it in its PRIVATE host-configuration repo (the role below), beside the reviewed
host files, as one companion page that maps every role on this page to its value.

## 1. The repository family

Each family member is one repository with one role. The dependency arrow points one way, toward the leaf:

```
products (an application, its data libraries)
   -> engines and libraries (numerics, optimisation, AI, documents, learning)
        -> the dev kit (dev-lab: dev tooling, host ops, supervision)
             -> the leaf (lab-commons: logging, paths, config, launch, units)
host configuration (private): data only, consumed by the dev kit's ops door on each host
```

| role | what it holds | depends on |
|---|---|---|
| leaf | the shared runtime every member imports (`lab_commons`) | nothing in the family |
| dev kit | `dev_lab.dev` (forge, integrator, hooks, refusals), `dev_lab.ops` (host roles), `dev_lab.supervise` | the leaf |
| engine / library | a solver engine, an optimiser, an AI layer, a document or learning toolkit | the leaf; the dev kit as a `test` extra |
| product | an application that mounts engines (as git dependencies or submodules, [components](components.md)) | engines, libraries, leaf, dev kit |
| data library | a data-only repo pinned by its product as a data dependency; its PRs run the product's consumer tests (`dev_lab.dev.dataconsumers`) | -- |
| host configuration | `hosts/<server>.toml` (each host's `supervise.toml`) and `family.toml` (the shared `[family]` layer) | read by `dev_lab.ops` |

- The member list of a machine is its machine file's `[repos]` (`dev_lab.dev.family.members`); everything that
  lists repos derives from it. A new member is onboarded with one call ([onboarding](onboarding.md)).
- A member's direct family dependencies are its `pyproject.toml` git dependencies, pinned by its `uv.lock`;
  `python -m dev_lab.dev.dep` moves a pin, and a local checkout is used only when the machine file names it.

## 2. The branch flow

```
lane/* feat/* fix/*   (local only; fan-out in worktrees)
   -> pr/<feature>    (one long-lived pushed branch per session)
        -> integrate/main   (the forge merges a green, reviewed PR; merges only)
             -> main        (integrate promote: fast-forward only, every part a full PASS)
```

- Child branches are local; one `pr/<feature>` per session is what is pushed ([one branch per session](branch-set.md)).
- A PR targets the integration branch (`PRS-TARGET-INTEGRATION`); the integration branch takes only forge merges
  (`INTEGRATION-IS-MERGES-ONLY`, from `[tool.dev_lab.integrator] merges_only_since` / `pr_merges_since`).
- A child takes integration by `forge sync` (a merge, never a rebase); the forge auto-syncs a head whose lock alone
  conflicts ([integration](integration.md#auto-sync-the-forge-syncs-a-pr-head-whose-lock-alone-conflicts)).
- `integrate promote <sha>` moves the trunk by fast-forward only when every required part stands PASS at scope
  `full` ([promoting the trunk](integration.md#promoting-the-trunk)). On GitHub the rendered `ci.yml` runs it on a
  promotion event; on a self-hosted forge the forge host's `[ops.promote]` role runs it on its schedule.
- Branch names, the trunk and the integration branch are `[tool.dev_lab.integrator]` (`dev_lab.dev.lanepolicy`).
  A repo whose `integration` equals its `trunk` (a data-only host-configuration repo) merges straight to it.
- Detail: [branch layers](branch-layers.md), [the integration branch](integration.md), [verdicts](verdict-model.md).

## 3. Forges and identities

A family may span two forges: GitHub for public members and a self-hosted Gitea for private ones. The verbs are
the same on both (`python -m dev_lab.dev.forge ...`, the backend chosen by the URL's host,
`dev_lab.dev._forgebackends`). Every identity has ONE role, and each token lives in exactly one declared place.

### Gitea (self-hosted): accounts by role

| role | used for | where its token lives |
|---|---|---|
| developer (a human) | local work on a workstation only: push, PRs | the workstation's git credential store (`forge auth login`) |
| administrator (a human) | the Gitea admin; no standing token -- `dev_lab.ops.giteaadmin` mints a one-use admin token and deletes it; may be the declared break-glass login | none standing; break-glass: `[ops.breakglass.tokens]` file on the forge host |
| `read` machine account | every server that pulls code, research hosts included; ONE token per host | `[ops.config] token_file` on each host; a research account's git credential store |
| `write` machine account (CI) | posts test verdicts (`tests/<part>` statuses) from verify accounts | the verify account's git credential store |
| `review` machine account | posts reviews from the judge host only | `[ops.judge.tokens]` file on the judge host |

- Machine accounts are DECLARED, `[ops.forge.accounts.<login>] role = "read"|"write"|"review", repos = [...]`, in the
  forge host's config, and made only by `forge account ensure` (`dev_lab.ops.forgeaccounts`). The granted permission
  is `ROLE_GRANTS` (`dev_lab.ops.giteaadmin`): `read -> read`; `write` and `review -> write`, because Gitea posts a
  commit status only for a code writer -- the reviewer's real bound is its token's scopes
  (`write:repository,write:issue,read:user`).
- A `read` login is refused any scope outside `read:*`. A research host's deploy refuses a writer credential
  (`forge auth role`, `dev_lab.dev.hpcaccount`).

### GitHub: identities by role

| identity | used for | where its credential lives |
|---|---|---|
| the developer's personal account | local work only | the workstation's git credential store |
| the Actions token (`github-actions[bot]`) | CI parts, the merge tick (`merge-tick.yml`), `integrate promote` (`ci.yml`) | per job, `${{ github.token }}`; nothing stored |
| the judge App | review verdicts: the `JUDGE_CHECK` check run on integration PRs | private key on the judge host, `[ops.judge.apps]` |
| the ops App | break-glass merges and mirrors; listed as the ruleset's bypass actor | private key on the forge host, `[ops.breakglass.apps]` |

- No personal access token sits on a server: break-glass on GitHub is the ops App (`app_of_forge`,
  `dev_lab.ops.config`), and a live PAT there is refused.

### Protection is declared, then applied

- `[tool.dev_lab.protection]` in each repo's `pyproject.toml` declares, per forge host, the ONE bypass identity
  (`breakglass`: on GitHub a list of `app:<id>`/`role:<r>`/`team:<id>`, on Gitea a login) and who may push the trunk
  (`promote`, Gitea). Branches come from `[tool.dev_lab.integrator]`, required contexts from the rendered workflows
  (`required_contexts`); no approval is ever required (the judge is advisory).
- `python -m dev_lab.dev.forge protect plan|check|apply` renders it onto the forge (`dev_lab.dev.forgeprotect`).
  `apply` is an administrator's verb, run from a workstation after reading `plan`; CI never runs it.
- Who produces is the forge's data (`_forgebackends.Backend.producers`, user rulings 2026-11-11): a GitHub repo is
  gated and promoted by its Actions jobs alone -- no forge serve host, cluster or workstation; a part no
  hosted runner produces (a heavy test) is kept and off its gate (`jobparts.off_gate`). Gitea wires every producer.
- Review: `[tool.dev_lab.review] where = "judge"` (either forge) sends every PR to the judge host, whose verdict is
  ADVISORY (`_forgebackends.ADVISORY`): posted as information, never waited on by `tests/merge-ready`
  ([review](forge.md#a-review-judged-on-its-own-host-forge-review-prepare--judge)).

## 4. Hosts and their roles

Every server runs the ONE ops door, `python -m dev_lab.ops --config /etc/dev-lab/supervise.toml <verb>`, whose
config is that host's reviewed file in the host-configuration repo. Roles are tables; a host carries the ones it
declares (`dev_lab.ops.config.load`).

| host role | tables it declares | what it runs |
|---|---|---|
| forge host | `[ops]`, `[ops.promote]`, `[ops.breakglass]` (+ `.tokens`, `.apps`), `[ops.consent]`, `[ops.backup]` (export), `[ops.forge]` (+ `.accounts.*`), `[ops.caddy]`, `[ops.access]`, `[ops.supervise]`, `[ops.upgrade]`, `[ops.config]` | the Gitea, promotion, the break-glass server and its `tick`, the consent issuer, backup export, the reverse proxy allowlist, supervision |
| backup host | `[ops.backup]` (pull, `.offsite`), `[ops.supervise]`, `[ops.access]`, `[ops.upgrade]`, `[ops.config]` | backup pull and offsite copy, mirrors, a health probe of the forge host |
| judge host | `[ops.judge]` (+ `.tokens`, `.apps`), `[ops.access]`, `[ops.upgrade]`, `[ops.config]` | `forge review judge` per declared repo on its schedule |
| serve host (workstation) | the machine file's `[serve]`, `[capabilities.*]` | `forge serve` (claims shas, posts parts) -- [the forge](forge.md), [adding a workstation](adding-a-workstation.md) |
| verify account (HPC) | a `[[hpc.grant]]` in `family.toml` | `hpcaccount tick` from cron: claims parts with the `write` login ([HPC](hpc.md)) |
| research account / host | a grant or a host with the `read` login | pulls code, submits research jobs; never posts ([from a workstation](hpc-from-a-workstation.md)) |
| CI runner | the forge's Actions runners | the rendered workflows (`dev_lab.dev.ciworkflows`) |

- `[ops.access]` is the agent's troubleshooting login: ssh key AND the user's TOTP (pam_oath, a root-only secret),
  sudo narrowed to exactly the listed `commands` (`dev_lab.ops.access`).
- `ops upgrade` installs dev-lab at the tip of `[ops.upgrade] ref` with the family pins of THAT commit's lock,
  self-checks, and rolls back on failure (`dev_lab.ops.upgrade`).

## 5. Consent: one code per shown plan

- THE CLUSTER CODE is the 6-digit TOTP code the user types: every ops host of a cluster (its consent issuer
  and each `[ops.access]` login) holds the SAME TOTP secret, so one Authenticator entry answers for the whole
  cluster, never one per host. Every prompt, refusal and doc names it "the cluster code".
- The forge host's consent ISSUER alone holds the cluster's TOTP seed and an Ed25519 key (`dev_lab.ops.consent`);
  verifiers hold the public key; clients hold nothing. A credential is signed for ONE action of the registry
  (`dev_lab.ops.consent.actions`) and ONE subject (a digest), and an irreversible action registers its single use
  online.
- A plan (`{"host", "grants": [...]}`, at most `MAX_GRANTS` = 16) is shown to the user with its digest
  (`python -m dev_lab.ops.consent plan <plan.json>`); one cluster code from the user buys one credential per grant AND opens
  the host session. A plan changed after it was shown has another digest and is refused (`dev_lab.ops.consent.plan`).
- `sshhold` holds that session: one authentication per work session, every later command rides it
  (`python -m dev_lab.dev.sshhold open <dest> --hours H --plan <plan.json> --digest <D>`, `run`, `close`,
  `status`; `--jump <bastion>` for a host behind a bastion that shares the TOTP secret). The code reaches ssh only
  through `SSH_ASKPASS`, never argv, disk or a log (`dev_lab.dev.sshhold`).
- A code is the user's own, typed for THIS plan; no host step needing one runs without it.

## 6. Break-glass waves

- Break-glass merges a PR past the review AND its tests (user ruling 2026-11-11): unrun, pending or red, it merges
  inside an open wave, and its test state at merge time -- `passed`, `red: <contexts>` or `untested` -- is named in
  the PR comment, the audit line and the wave's summary (`tests_at`, `dev_lab.ops.breakglass`). The host's own
  sweep still lands only green PRs (`dev_lab.ops.wavesweep`); an untested merge is always an explicit request.
- It runs only inside a WAVE the user opened with a `breakglass.wave` credential whose params are the window
  (`hours`) and the cap (`max_merges`), each up to the host's `[ops.breakglass] wave_hours_max` / `max_merges_max`
  -- above a ceiling it is refused, never clamped. The merge that reaches the cap ends the wave.
- While a wave is open, the host's `tick` sweeps it: each green, non-draft, CURRENT (`pr-current` success) PR in
  `[ops.breakglass] repos` lands; a refused one is skipped with its reason (`dev_lab.ops.wavesweep`).
- Each merge carries a `Break-Glass: <reason>` trailer (at least `min_reason` characters) that opens a follow-up
  issue; the wave sends ONE summary alert when it ends. Client: `python -m dev_lab.dev.forge breakglass
  open|close|ack|status` and `forge pr breakglass` (`dev_lab.dev.forgebreakglass`).

## 7. Configuration files

| file | where | owns | reader |
|---|---|---|---|
| machine file | `lab_commons.home.config_path()`, under the machine home | `[repos]`, `[serve]`, `[capabilities.*]`, `[workstation]`, `[ssh.hold]` (`max_hours`, `idle_minutes`), `[tools]` | `lab_commons.config`, `lab_commons.home` |
| family layer | `family.toml` in the host-configuration repo | `[[hpc.grant]]`, AI spend caps, the review month -- a machine file restating a key is refused | `lab_commons.config` `[family]` |
| repo declarations | each `pyproject.toml` | `[tool.dev_lab.integrator]`, `.review`, `.protection`, `.ci` | `dev_lab.dev.lanepolicy`, `forgeprotect`, `ciworkflows` |
| host file | `/etc/dev-lab/supervise.toml`, reviewed as `hosts/<server>.toml` | `[ops.*]`, `[components.*]`, `[alerts]`, `[cycle]` | `dev_lab.ops.config`, `dev_lab.supervise.config` |

- A host file changes only through `config apply` (`dev_lab.ops.configdoor`): routine keys (`configdoor.ROUTINE`)
  on the operator's word, every other key with an `ops.config` credential bound to the candidate's sha256. A host
  whose `[ops.config]` declares a `schedule` runs `config tick`: routine changes merged in the host-configuration
  repo apply by themselves; a boundary change is parked until consented ([forge](forge.md#changing-a-forge-hosts-configuration)).
- A retired `[ops]` shape is upgraded on read in ONE place, `dev_lab.ops.configupgrade` (`FORMATS-UPGRADE-ON-READ`);
  the next `config apply` writes the new shape. A file holding both the old and the new shape is refused.
- No secret value enters any of these files: they name paths only. `python -m dev_lab.ops.configcheck` enforces it
  on every PR of the host-configuration repo and labels a boundary change `needs-consent`.

## 8. Setting up

### A new development workstation

1. Install `git`, `uv`, `node` (and `codex` for a serving box) -- [adding a workstation](adding-a-workstation.md#deploy-step-by-step).
2. Clone each member beside its siblings and record it in the machine file's `[repos]` (name -> absolute path).
   Further checkouts go under `<repo>/.claude/worktrees/<name>` ([worktrees](worktrees.md)).
3. Bootstrap each repo's venv through its install door (`uv sync --frozen`, or the product's bootstrap script).
4. Give the box its forge credentials with the developer's OWN account: `python -m dev_lab.dev.forge auth login`
   per forge host, or move them from an old box with `forge auth export | ssh <box> "... auth login --from-file -"`;
   verify with `auth status` ([credentials](forge.md#credentials)).
5. Install the hooks: `python -m dev_lab.dev.hook_install --install`.
6. To also SERVE parts: `python -m dev_lab.dev.workstation template --role light --repos ...`, then the deploy
   ([adding a workstation](adding-a-workstation.md)).
7. For hosts behind a TOTP: optionally set `[ssh.hold] max_hours` / `idle_minutes` in the machine file.

### A forge host

1. Write `hosts/<server>.toml` in the host-configuration repo by PR (the tables in section 4); it is reviewed and
   checked like code.
2. On the host, as root once: create the venv at `[ops] python` and install `dev-lab[ops]`; place the file at
   `/etc/dev-lab/supervise.toml`.
3. `python -m dev_lab.ops --config /etc/dev-lab/supervise.toml install` renders every unit, sudoers line, sshd
   block and PAM include, and prints the root `next_steps` (accounts, `systemctl daemon-reload`, sshd test and
   reload). It is idempotent (`dev_lab.ops.install`).
4. Place the cluster's ONE TOTP secret: `consent enrol` on the cluster's first host only, `access adopt` on every
   other (the secret the user's Authenticator already holds); `consent keygen` makes the issuer key if absent.
5. Place each declared secret: `python -m dev_lab.ops secret place --path <declared path> --credential <cred>`
   with the content on stdin (`dev_lab.ops.secretplace`: 0600, owned by the declared role's user, only a sha256
   prefix ever printed). The break-glass forge token or App key, the promote credential, the config token.
6. Declare the machine accounts under `[ops.forge.accounts.*]`, then `forge account ensure --login <L>` for each.
7. From then on: `upgrade` moves the code, `config apply` / `config tick` move the config.

### A judge host

1. Its host file declares `[ops.judge]` (`user`, `home`, `schedule`, `repos`) with `[ops.judge.tokens]` for each
   Gitea host (the `review` login's token file) and `[ops.judge.apps]` for GitHub (`app_id`, `key_file`).
2. `install`, then `secret place` the Gitea token and the App key into the declared paths; a host reachable only
   through a bastion is reached with `sshhold open --jump`.
3. Each repo names the judge in `[tool.dev_lab.review]` (`where = "judge"`, `judge_login` or `judge_app`) and is
   listed in `[ops.judge] repos`; then `forge protect apply` makes the judge's verdict required.

Its review model keys and the family spend cap arrive as ONE consent plan of three steps
(`python -m dev_lab.dev.planrun preflight|run`, one code):

1. `config apply` -- the host file declares `[ops.judge] keys_file` and `[ops.config] family = { file = "family.toml",
   to = "/etc/dev-lab/family.toml" }`, with `[ops.judge.family] source = "/etc/dev-lab/family.toml"`. The door takes
   `family.toml` from the same reviewed source and ref and places it (0644, no secrets); a family change is boundary.
   A declared keys_file not yet placed loads; one present but not a `[keys]` bundle refuses.
2. `secret place --path <keys_file>` with `"stdin_task": "pr-review"`: the task's bundle streams from this machine's
   `forge secrets` store into the verb's stdin -- no file anywhere, never on a command line or the audit.
3. `install` -- it refuses while the keys_file is declared but not placed, and names step 2.

A step whose OUTPUT is the secret (a `forge token mint`) declares `"stdout_local": "<relative name>"` (no `..`): the
output goes owner-only to `outputs/<name>` under this machine's private consent state (`planrun.stdout_path`, never a
checkout) and the run prints only `wrote <path> (sha256 <12 hex>, <n> bytes)`; a failed step prints its exit status
and `output withheld`, and writes nothing.

### A CI verify account (HPC)

1. Add its `[[hpc.grant]]` to `family.toml` (user, login hosts, scheduler account, partitions, setup).
2. Mint its token from the `write` login (below) and store it ON that account with `forge auth login`;
   `forge auth check --url <repo>` proves a serve tick can post there.
3. `python -m dev_lab.dev.hpcaccount deploy` (or `deploy-fleet` from a workstation) installs the account's checkout,
   venv and cron line ([HPC](hpc.md#deploy-one-line-per-account)).
4. A research account gets the `read` login instead; its deploy refuses a writer.

## 9. Rotating a token

All on the forge host through the `ops` login, each step under a single-use credential bound to its request's
digest (`--subject` prints it; `dev_lab.ops.forgerequests`):

```
python -m dev_lab.ops --config /etc/dev-lab/supervise.toml forge token list   --login <L>
python -m dev_lab.ops --config /etc/dev-lab/supervise.toml forge token mint   --login <L> --name <N> --scope <S> --rotate
python -m dev_lab.ops --config /etc/dev-lab/supervise.toml forge token mint-batch --login <L> --item <N>:<S>... [--rotate <N>]...
python -m dev_lab.ops --config /etc/dev-lab/supervise.toml forge token revoke --login <L> --name <N>
```

1. Name tokens per host (one token per login per host), so one host's token is revoked without touching another.
2. `mint --rotate` deletes the old token first and prints the new one ONCE to stdout; redirect it into a git-ignored
   file, never a terminal, log or chat. `mint-batch` mints up to 16 of one login's tokens for one code.
3. Place it where its role says: `secret place` for a host file (section 3), `forge auth login --from-file -` for a
   git credential store; verify with `forge auth check` / `auth status`.
4. Revoke the replaced token by name; `revoke` of an absent name reports it absent, so it can be re-run.
5. A GitHub App key rotates in GitHub's App settings (owner only), then `secret place` into the declared `key_file`.
