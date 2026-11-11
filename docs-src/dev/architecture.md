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
- Break-glass may bypass the review AND the tests inside an open wave, audited with the test state at merge.
  Today it bypasses the review only (`dev_lab.ops.breakglass::_tests_stand`); the change is in progress on
  `pr/break-glass-bypasses-the-tests`.
- The judge's review is ADVISORY on both forges, never a merge gate (gap: contract 4 below, article 3).

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
- **Today.** A claim is a `pending` status; the EARLIEST live claim by forge order wins
  (`dev_lab.dev.forgeclaim::assess`, `claim`); the lease is `DEFAULT_LEASE` (6 h) on the forge's clock
  (`forge_now`) and a lapsed one is retaken. A released claim with `producer.RETRYABLE` is claimable again.
  Every write is journaled and replayed until acknowledged, never double-posted (`dev_lab.dev.forgeoutbox`).
  A cluster run's file is keyed by repo + sha + platform + scope (`dev_lab.dev.forgerunstate`).
- **Gap.** The claim is post-then-reread, not compare-and-swap: a loser may already have posted its `pending`,
  and the winner's renewal and a stale retake race on one context. Two verification accounts finishing the same
  part both publish; nothing makes the second a no-op beyond "latest wins" (contract 1).

### 4. Authorization

- **Contract.** One consent grant permits one action, on one subject, within its scope and expiry, once, and is
  audited; a plan changed after approval is refused.
- **Today.** A credential is Ed25519-signed over every field: `action`, `subject`, `params` and `params_hash`,
  `scope`, `cap`, `issued`, `expires` (`dev_lab.ops.consent.credential::verify`). The action registry is
  `dev_lab.ops.consent.actions.ACTIONS`. A plan's digest is shown before the code and a changed plan is refused
  (`dev_lab.ops.consent.plan::load`); the issuer records that digest in its append-only ledger
  (`issuer.Issuer.issue_plan`). An irreversible use is registered online, failing closed
  (`dev_lab.ops.consent.client::redeem`).
- **Gap.** The plan digest is not a signed credential field, so a verifier cannot tie a use to the shown plan
  without the issuer's ledger. A `breakglass.wave` is redeemed with no subject (`redeem(subject=None)`): it
  authorizes any PRs up to `max_merges` inside its window, each pinned only to the head shown. The review is
  still a merge gate (`dev_lab.dev.reviewgate::review_missing`), not advisory.

### 5. Generated artifacts

- **Contract.** dev-lab generates every family file a member repeats; a hand edit is detected; a generator change
  is shown not to change unrelated repos.
- **Today.** `dev_lab.dev.famfiles.PROJECT_FILES` lists every project file and its owner; `famfiles` renders
  them (`render_all`). Workflows are rendered from TOML and the drift check compares rendered bytes, refusing a
  hand-written one (`dev_lab.dev.ciworkflows`, stamp `RENDERED_BY`). The dev index table is
  `devdocs::pointer_table`. A lock left behind its dependencies alarms (`dev_lab.dev.drift`).
- **Gap.** No check shows a generator change leaves unrelated repos' renders unchanged; each repo finds out at
  its next render. Consumer tests hand-copy rendered lists: the motor product's
  `test_the_locked_gitea_workflows_keep_the_trusted_review_door.py` pins `{'merge.yml', 'review.yml'}` and
  its shared-registry adoption test pins a tuple of rule IDs, instead of reading them from dev-lab.

### 6. Failure ownership

- **Contract.** Every non-PASS names its owner class: code, environment, scheduling, vendor licence, network, or
  status publishing; only a code failure is the author's red.
- **Today.** Code: a part `failure` (FAIL). Environment and outages: `error` with `released: unreachable`
  (`producer.RETRYABLE`, re-claimed) or `released: inconclusive (exit 3) -- no part`
  (`dev_lab.dev.producer::release_reason`). Scheduling: `released: the box killed it past its declared ...`
  and a lapsed lease. A commit's own defect: `refused at this commit:` (`forgeclaim.REFUSED_AT_COMMIT`). Network
  and rate limits: classified and retried (`dev_lab.dev.forgefailure::diagnose`). Status publishing: the
  outbox holds and replays (`forgeoutbox`).
- **Gap.** The class lives only in description prose: every non-code failure posts `error`, which both forges
  render as the same red as a FAIL, and `parts_of` reads it as one unsettled problem. There is no vendor-licence
  class at all; a licence outage reads as a FAIL or as `unreachable`, by what the producer chose to declare.

## The constitution

| # | article | today |
|---|---|---|
| 1 | Humans hold final authority over high-risk actions; an agent cannot widen its own permissions. | implemented: consent door, `CONSENT-CODE-FROM-THE-USER` |
| 2 | dev-lab governs family development and carries no business or compute duty that is not its own. | implemented |
| 3 | GitHub toolchain repos' merge gate does not depend on HPC, workstations or the judge being online. | target: a merge waits on `tests/review` (contract 4) |
| 4 | Gitea business repos carry heavy verification and cross-repo integration; test definitions are not needlessly copied. | target: hand-copied lists (contract 5) |
| 5 | Each fact has one authoritative source; derived artifacts are maintained by deterministic generation. | partly: no cross-repo render check (contract 5) |
| 6 | `integrate/main` may fail; a normal promotion of `main` requires a green verification of the exact commit. | partly: required set, env and policy unchecked (contract 2) |
| 7 | Break-glass is an explicitly authorized, fully audited exception and does not change test facts. | target: test bypass in progress; wave not bound to subjects (contract 4) |
| 8 | Every HPC operation follows the one door, rate limit, quota protection and cleanup rules. | implemented: `HPC-THROUGH-THE-DOOR` |
| 9 | Every CI status is traceable to a specific commit, test, environment and execution record. | target: no env in the status (contract 1) |
| 10 | Reuse existing capability first; a new service is introduced only when a real need proves it necessary. | implemented as review practice; nothing enforces it |
