# dev-lab

The development system of the lab family: the forge, the hooks, the gate and `verify`, lane and worktree mechanics.

## How a change lands

The family flow, stated once in [the integration branch](docs-src/dev/integration.md):

- Cut `pr/<topic>` from `origin/integrate/main`, measure what you touched, commit, push, open a pull request.
- A producer claims the pushed head and posts `tests/<part>`; the FORGE merges the PR once every part
  stands PASS, the head merges cleanly and the merge passes the audit.
- `main` moves only by `integrate promote <sha>` on a full PASS.

The mechanisms are documented in `docs-src/dev/`; this repo declares its names in `pyproject.toml`.

<!-- BEGIN dev-lab family section -->

## Family principles

_Rendered by `dev_lab.dev.agentsection` from `dev_lab.dev.principles`; a hand edit here is refused._

- **First principles** (`first-principles`): Derive from the actual system and current needs, not habit or precedent;
  state shaping assumptions.
- **Discard historical baggage** (`no-historical-baggage`): Remove obsolete structures, duplicates and dead paths no
  current need uses -- never a capability.
- **Occam's razor** (`occams-razor`): Simplest design meeting the need; nothing hypothetical; never a capability.
- **Single source of truth** (`single-source-of-truth`): Each fact lives in one place; all else derives from it.
- **Layered decoupling** (`layered-decoupling`): Depend one way through narrow interfaces; never into internals or
  upward.
- **Names match what they do** (`names-match-behaviour`): A name says what the thing does now.
- **No backward compatibility** (`no-backward-compatibility`): No shims, aliases or dual paths for old callers; callers
  move with the change.
- **Progressive disclosure** (`progressive-disclosure`): An entry point states what is needed first and points to
  detail; no duplication across levels.
- **Keep every valuable parameter and option** (`keep-valuable-options`): Generality is a requirement: keep every
  parameter and option a real case uses or plausibly needs. A reference match ADDS a selectable option and never
  replaces or deletes the alternative; numerical method choices are options even with no current caller.
- **Every wall teaches** (`every-wall-teaches`): Every refusal or failure an agent hits names its cause and its door;
  one that does not is a mechanism gap, and closing it (a hook row, a remedy, a test) comes before the task. Never route
  around a wall or hand the user a command. The loop: docs-src/dev/feedback.md.
- **Fan out without a barrier** (`no-barrier-fan-out`): Parallel work is independent items, each landed the moment it is
  done; nothing waits for the slowest sibling -- no barrier-style orchestration (e.g. a dynamic workflow that joins all
  agents) unless a step truly needs every result. How: docs-src/dev/fanout.md.
- **Deliver an image by its absolute path** (`images-by-absolute-path`): An image handed to the user is named by its
  ABSOLUTE path, never a relative one (IMAGES-BY-ABSOLUTE-PATH).
- **A worktree is named for its task** (`worktree-names-its-task`): A worktree's name has a physical meaning tied to its
  task; a hash-like name (`agent-<hex>`, an appended hash) is forbidden (WORKTREE-NAMES-ITS-TASK).

## Family workflow

_Each rule is cited by ID; its full statement and refusing mechanism live in `dev_lab.dev.rules`._

- `SHARED-CHECKOUT`: A box holds a SHARED, possibly concurrent checkout: there is NO single-agent mode, the remote IS
  the only shared medium, pushing is the obligation rather than the last step of landing, and a verdict cannot be
  delegated to someone who cannot see the code.
- `ONE-BRANCH-PER-SESSION`: The integration branch is the only long-lived branch a session works into: a pushed head is
  `pr/<task-slug>/<feature>`, one feature per PR, and every other branch is merged and then deleted, never left behind;
  a repo`s long-lived branches are DECLARED (the trunk plus the integration branch) so anything else on origin or on
  this box is debt, and unpushed work is reported, never deleted silently.
- `PRS-TARGET-INTEGRATION`: Every pull request targets the integration branch, one opened against the trunk is
  retargeted with a comment saying why, and each child branch carries ONE integration comment (or, without a PR, one
  `integration` commit status) updated in place by `forge integration`, never a new one per tick.
- `DOWNSTREAM-SYNCS-INTEGRATION`: A child branch (a lane, a feat branch, a pull-request head) merges ONLY the
  integration branch, so another child`s work reaches it once, through integration, unless the owner opts in to watch
  named refs recorded in the checkout`s own git config (`branch.<child>.labSyncFrom`), never in a file, and `forge sync`
  merges integration first, then the watched refs, refusing any other ref by name.
- `SUBAGENT-NO-PUSH`: A subagent never publishes (no push, no PR opened or readied, no skipped hook): it commits on its
  lane and hands the SHA back to the main session, which merges and pushes, the forge produces the verdict
  (VERDICTS-FROM-THE-FORGE), and a targeted measure of the tests it touched stays its own.
- `VERDICTS-FROM-THE-FORGE`: A verdict is a fact about (tree, env key, part), produced ONCE after the push by the forge
  serve host that claims its `tests/<part>` part and read from the forge: no pre-push hook runs a test, a full tier
  refuses outside the producer naming the remedy (push, then read the part), a targeted measure needs no claim, and a
  producer cites a stored PASS of its key rather than re-run.
- `TRUNK-MOVES-BY-FAST-FORWARD`: The trunk moves only by fast-forward to an integration commit whose every required
  `tests/<part>` part stands PASS at scope full, through `integrate promote`; it refuses with the missing parts named
  and the emergency door, and refuses a trunk that cannot fast-forward rather than merging into it.
- `MERGE-OR-DELETE`: A merged branch is DELETED and an unmerged one is MERGED, no third state: an `archive/*` tag or
  untracked rename hides work and is debt -- `branchset` lists it, deletes it when a declared branch holds its tip, else
  names it to merge.
- `AGENT-GUARD`: A hand-written test invocation, a bare network git verb and a stash are refused by the shared deny
  machinery rather than by prose, so the refusal is identical in every repo that adopts it.
- `NETWORK-RETRY-THEN-REPORT`: The forge is a REMOTE service: a network verb goes through the retry wrapper rather than
  being called directly, and a write that still fails is REPORTED with its diagnosis instead of hammered.
- `PRODUCTION-ENTRY-POINT`: Reproduce a behaviour through the PRODUCTION entry point, never an ad-hoc script handed out
  beside it, and treat a behaviour not reachable from there as a gap to FIX, the boundary being the SUBJECT, not the
  tree the code happens to live in.

<!-- END dev-lab family section -->
