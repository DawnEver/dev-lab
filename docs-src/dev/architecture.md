# The family architecture

The normative specification of how the family is developed: the principles, the two kinds of repository, the
branch flow, the compute pool, consent, feedback, six contracts and the constitution. This page is the single
source; every other page owns a mechanism and points here for the WHY. Each contract states the rule, the code
that implements it today, and the GAP where today's code falls short -- a gap is a work item, never a licence.

The concrete instance (hosts, accounts, addresses) is never written here ([topology](topology.md), first lines).

## Principles

First principles, no historical baggage, Occam's razor, single source of truth, layered decoupling, names match
behaviour -- each in its place. Their statements live once in `dev_lab.dev.principles`; a repo renders them into
its `.claude/rules/principles.md`.

## Two kinds of repository

| kind | members | merge gate | heavy tests |
|---|---|---|---|
| toolchain (GitHub) | dev-lab, lab-commons, ai-lab, numerics-lab, document-lab, learn-lab, the optimisation library, the winding library | GitHub Actions ONLY: no HPC, workstation or judge dependency | stay in the tree, marked heavy, excluded from the GitHub gate; exercised by the business repos' unified tests |
| business (Gitea) | the motor product, the winding application | forge producers ([the forge](forge.md)) | run here: unified and heavy verification, cross-repo integration |

- A business repo's test statuses are posted DIRECTLY by the HPC verification accounts (the `write` machine
  account, [topology](topology.md#3-forges-and-identities)); no relay re-posts them.
- Heavy is declared data ([testing discipline](testing-discipline.md)); a test definition is never copied into
  the repo that exercises it.

## The branch flow

`pr/*` -> `integrate/main` -> `main`. `integrate/main` may be red: a PR merges once its tests have RUN and every
red is on record (tested, not green). `main` moves only by `integrate promote`, a fast-forward to an integration
commit that is green. Mechanism: [branch layers](branch-layers.md), [the integration branch](integration.md).

## HPC: one pool, two uses

The clusters are the compute pool for business-repo tests AND a research platform
([HPC clusters](hpc.md), [research from a workstation](hpc-from-a-workstation.md)). Both share one set of
mechanisms; each is owned where it is linked:

- The key-only doors `python -m lab_commons.hpc plan|submit|status|gather|retry|run|clean|log` (`log --tick`
  included), and nothing else: `HPC-THROUGH-THE-DOOR` ([refusals](refusals.md#hpc-through-the-door)).
- One shared ssh connection per host, a per-host rate limit with pacing, a 60 s poll floor, and
  `clean --timeout` (`lab_commons.hpc.sshgate`, same section).
- The quota guard, leases and the stray census (`lab_commons.hpc.lease`, `lab_commons.hpc.home.strays`,
  [HPC clusters](hpc.md#grants-the-machine-file)).
- Retention with an in-flight mark, re-checked before removal (`dev_lab.dev.retentionplan`,
  [artefacts](artefacts.md)).

## Consent and break-glass

- The consent door: the user's TOTP code, shown ONE plan digest, a preflight before the code is spent, and one
  single-use signed credential per grant (`dev_lab.ops.consent`, [topology](topology.md)).
- Break-glass bypasses the review AND the tests inside an open wave, each merge audited with its test state at
  merge (`dev_lab.ops.breakglass::tests_at`) under the consent that opened the wave.
- The AI review is ADVISORY on both forges: it runs and posts, the merge decision reports it, nothing waits on it
  (contract 4 below, article 3).

## Feedback

A session hears every PR it touched: the session PR record (`dev_lab.dev.sessionprs`), `forge watch --session
<id> --stream` (`dev_lab.dev.forgewatch`), and the `Stop` gate on the session's own PRs (`dev_lab.dev.pushwatch`).

## The six contracts

### 1. Test identity

- **Contract.** A result is keyed by (repo, commit, test id or part, env key, verification policy). Two results
  that differ in any field are two facts; neither may overwrite the other.
- **Today.** A forge status is keyed by (commit, context `tests/<part>`) and the LATEST per context is read
  (`dev_lab.dev.platformparts::parts_of`). The description carries scope, ran, hands and carried/cited
  (`platformparts::_DESCRIPTION`); the env key lives in the attached run record and in the verdict store's
  `ContentKey(tree, env, part)` (`dev_lab.dev.verdictstore`, `dev_lab.dev.verdictenv::verdict_env`).
- **Gap.** The status carries no env key and no policy (test-definition) version, so a second post of the same
  part on the same commit from another environment or another test version OVERWRITES the first, and the
  promotion reads whichever came last.

### 2. Promotion

- **Contract.** `main` is promoted to exactly the commit that was verified: an integration commit, fast-forward,
  every REQUIRED part PASS at scope full, in a declared env and policy, with no failure inherited unseen.
- **Today.** `dev_lab.dev.integrate::decide` refuses a sha not on `origin/<integration>`, a non-fast-forward, and
  any part not PASS at scope `full` (`platformparts::standing`). A part cited from the same tree or carried from
  an ancestor names its origin sha in the description (`dev_lab.dev.forgecarry`). A break-glass merge commit is
  a commit like any other: it is promoted only on its own parts.
- **Gap.** The required set is DERIVED from what was posted (`platformparts::derived`: the base part, every
  posted part, every part one hands to), so a part never posted and never handed to is never required. No env
  or policy match is checked. A carried PASS is accepted without re-reading the source run's env.

### 3. Producer claim

- **Contract.** Exactly one producer runs a (commit, part); a claim is atomic, leased, recovered after a timeout,
  a retry keeps the result's identity, and publishing is idempotent across several verification accounts.
- **Today.** A claim is a `pending` status naming its owner (machine, login, cluster account); the holder is a pure function of the
  status history (`dev_lab.dev.forgeclaim::holder`, `assess`): replayed in forge order, the first claim takes
  the job, another owner takes it only if the holder's lease had lapsed by the forge clock at that post's
  `created_at`, and the holder's owner renews it. A loser posts nothing further; a stale retake while the
  lease is live, or an old owner's renewal after a retake, counts for nothing. The lease is `DEFAULT_LEASE`
  (6 h) on the forge's clock (`forge_now`). A result is posted only through `forgeclaim::publish`, which
  re-reads the history first: a settled context is a no-op and a claim that no longer holds withdraws; the
  outbox keeps the first result and drops an identical second (`dev_lab.dev.forgeoutbox`). A released claim
  with `producer.RETRYABLE` is claimable again. Every write is journaled and replayed until acknowledged.
  A cluster run's file is keyed by repo + sha + platform + scope (`dev_lab.dev.forgerunstate`).
- **Gap.** Neither forge offers compare-and-swap, so `publish` is read-then-post: a retake landing between
  its read and its post (possible only once the lease lapsed) lets both results reach the forge, and the
  outbox's first-result rule then decides. A result queued in the outbox (`platformparts.post`) is checked
  for duplicates there but not re-gated on the claim. A post the forge dates no `created_at` is judged at
  the reader's `now`.

### 4. Authorization

- **Contract.** One consent grant permits one action, on one subject, within its scope and expiry, once, and is
  audited; a plan changed after approval is refused.
- **Today.** A credential is Ed25519-signed over every field: `action`, `subject`, `params` and `params_hash`,
  `scope`, `cap`, `plan`, `issued`, `expires` (`dev_lab.ops.consent.credential::verify`). The action registry is
  `dev_lab.ops.consent.actions.ACTIONS`. A plan's digest is shown before the code and a changed plan is refused
  (`dev_lab.ops.consent.plan::load`); every credential issued from a plan SIGNS that digest as `plan`
  (`issuer.Issuer.issue_plan`), so `grant_plan`/`recover` refuse an answer of another plan and `planrun` carries
  only a credential whose `plan` is the plan it runs -- no ledger needed. An irreversible use is registered
  online, failing closed (`dev_lab.ops.consent.client::redeem`). A `breakglass.wave` is the user's one-code grant
  for a window (`max_merges`, `hours`); each merge is refused outside `[ops.breakglass] repos`, pinned to the head
  shown, and audited as (repo, PR, head, reason, tests) under the id of the credential that opened the wave
  (`dev_lab.ops.breakglass.Server`). The review is advisory: `dev_lab.dev.forgemerge::decide` never lists it as
  missing, merge-ready says why a head is unreviewed and the merged PR is told (`ready`), Break-Glass pushes
  never ask it (`dev_lab.dev.sessionbranch`); no branch protection requires `tests/review`
  (`dev_lab.dev.forgeprotect::required_contexts`).
- **Gap.** A wave's merges are bound to the grant only after the fact (the audit), not to subjects the user saw:
  by design, one code for a window. `redeem` itself does not compare `plan` -- a host verb redeems a credential
  without knowing which plan it runs; the client sides (`planrun`, `grant_plan`, `recover`) check it.

### 5. Generated artifacts

- **Contract.** dev-lab generates every family file a member repeats; a hand edit is detected; a generator change
  is shown not to change unrelated repos.
- **Today.** `dev_lab.dev.famfiles.PROJECT_FILES` lists every project file and its owner; `famfiles` renders
  them (`render_all`). Workflows are rendered from TOML and the drift check compares rendered bytes, refusing a
  hand-written one (`dev_lab.dev.ciworkflows`, stamp `RENDERED_BY`). The dev index table is
  `devdocs::pointer_table`. A lock left behind its dependencies alarms (`dev_lab.dev.drift`).
- **Today, cross-repo.** `dev_lab.dev.rendergoldens` renders every famconfig base, whole family file and workflow
  for the generic declaration fixtures in `tests/_render_fixtures/` and compares them byte for byte with
  `tests/_render_goldens/`: a generator change names each render it moves, and moving a golden is a reviewed
  `rendergoldens update`. Consumers read rendered lists from dev-lab -- `ciworkflows.base_names(forge)`, and
  `rules.enforced_ids(declared_absent)` for a registry adoption -- instead of copying them.
- **Gap.** The fixtures are representative, not the members' own declarations, and the agent-hook renderers
  (`agent_guard`, `hook_adoption`, `autodoors`) are not in the golden set. The motor product reads the lists only
  after it relocks onto the dev-lab commit that adds `enforced_ids`.

### 6. Failure ownership

- **Contract.** Every non-PASS names its owner class: code, environment, scheduling, vendor licence, network, or
  status publishing; only a code failure is the author's red.
- **Today.** One enum, `dev_lab.dev.producer::Owner` (`code`, `environment`, `scheduling`, `vendor-licence`,
  `network`, `status-publishing`). The forge keeps its four states; the owner is the `class=<owner>` field of an
  `error` description (`producer.owned`, read by `producer.owner_of`, tolerant of other `key=value` fields). A
  `failure` part is `code`. Every release names its class: `release_reason` and `box_release_reason`
  (environment, scheduling), a declared outage (`producer.unreachable` network / environment / scheduling /
  status-publishing, `producer.licence_outage` vendor-licence -- released `RETRYABLE`, re-claimed), a commit's own
  defect `refused at this commit:` (code), superseded and no-room releases (scheduling), a dead host's intent
  (environment). `platformparts.standing` reads the class: an `error` naming `class=code` is FAIL, any other
  class leaves the commit INCONCLUSIVE (never PASS, so it blocks promoting `main`) and its problem says
  "not the author's (class=...)"; `forgenotice` tells the author only of `code` reds.
- **Gap.** Contexts outside `tests/` (`forgeheadgate`, `forgemerge`, `forgereview`, `forgesecurity`) still post an
  unclassed `error`, read as unowned (not the author's). Both forges still render every `error` red; the class is
  readable in the description only.

## The constitution

| # | article | today |
|---|---|---|
| 1 | Humans hold final authority over high-risk actions; an agent cannot widen its own permissions. | implemented: consent door, `CONSENT-CODE-FROM-THE-USER` |
| 2 | dev-lab governs family development and carries no business or compute duty that is not its own. | implemented |
| 3 | GitHub toolchain repos' merge gate does not depend on HPC, workstations or the judge being online. | implemented: the review is advisory, never a merge condition (contract 4) |
| 4 | Gitea business repos carry heavy verification and cross-repo integration; test definitions are not needlessly copied. | implemented in dev-lab: lists read from `ciworkflows` and `rules.enforced_ids`; the motor product adopts at its next relock (contract 5) |
| 5 | Each fact has one authoritative source; derived artifacts are maintained by deterministic generation. | partly: `rendergoldens` pins every fixture render; the agent-hook renderers are outside it (contract 5) |
| 6 | `integrate/main` may fail; a normal promotion of `main` requires a green verification of the exact commit. | partly: required set, env and policy unchecked (contract 2) |
| 7 | Break-glass is an explicitly authorized, fully audited exception and does not change test facts. | implemented: a wave waives tests and review, audits each merge under its consent; merges bound after the fact (contract 4) |
| 8 | Every HPC operation follows the one door, rate limit, quota protection and cleanup rules. | implemented: `HPC-THROUGH-THE-DOOR` |
| 9 | Every CI status is traceable to a specific commit, test, environment and execution record. | target: no env in the status (contract 1) |
| 10 | Reuse existing capability first; a new service is introduced only when a real need proves it necessary. | implemented as review practice; nothing enforces it |
