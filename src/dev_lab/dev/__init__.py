"""``dev_lab.dev`` — dev-time guarantees, OPT-IN and never imported by the top level.

Tier 3, and the tier boundary is a real one. ``lab_commons``'s own pyproject states its tier-1
posture in its own words -- "*Tier 1 core deps only … a consumer that wants only logging installs
nothing heavier than this*" -- so a runtime consumer must not acquire a development system by
importing the package it already had. ``lab_commons/__init__.py`` does not import this subpackage,
in the same way and for the same reason that it does not import ``lab_commons.em``: importing
``lab_commons`` never pulls this in, and a consumer opts in explicitly, by the full path:
``from dev_lab.dev.verdict import Verdict``.

THE OPT-IN IS GATED BY THE ``dev`` EXTRA, which already exists and is the right one: it names ``pytest`` and
``ruff``, and those two ARE this subpackage's dependencies -- as executables rather than as imports. Nothing
here needs a new install, because the layer is stdlib plus tier 1: :mod:`lab_commons.resources` (the box
lock), :mod:`lab_commons.paths` (the repo root), and ``hashlib``/``importlib.metadata``. That is a
measurement, not an aspiration -- ``pip install lab-commons`` pulls nothing new, and a consumer that wants
only logging still installs nothing heavier than it did yesterday.

WHAT IS HERE, and the order is the order of dependency rather than of importance. A bullet reading
NOT RE-EXPORTED says one thing, stated once here instead of at each site: that module's own names
are too unqualified to survive being flattened into a namespace this wide.

* :mod:`dev_lab.dev.content` — a CONTENT address over the measured paths, the half of a verdict
  that a ``HEAD``-shaped stamp cannot supply; :mod:`lab_commons.envkey` keys the environment, the other half.
* :mod:`dev_lab.dev.logref` — the log a verdict carries, and the reader that re-derives it.
* :mod:`dev_lab.dev.verdict` — the algebra: ``(tree, env, selector, result, log)``.
* :mod:`dev_lab.dev.pytestout` — READING one test runner's stdout and nothing more: the escape
  strip, the anchored summary line, the collected count and the truncation vocabulary. Every reader
  answers ``None`` for a line never printed, never ``0``. NOT RE-EXPORTED.
* :mod:`dev_lab.dev.reports` — what those readings MEAN for a verify step: the exit-code table,
  the shortfalls, and the two-sided skip ratchet a project declares in ``allowed_skips``.
* :mod:`dev_lab.dev.verify` — the family's ONE entry point that PRODUCES one:
  ``python -m dev_lab.dev.verify`` runs ruff, ruff format and pytest, tees them into a log under
  ``.verify/``, and prints a stamped verdict -- the portable half of consumer-a's 1770-line
  gate runner, the half needing no case library, no solver and no vendor engine, so the three repos
  with no verdict-producing invocation at all now have the same one. NOT RE-EXPORTED for its own
  reason: it runs as ``__main__``, and importing it here makes ``runpy`` warn it was already loaded.
* :mod:`dev_lab.dev.profile` — ``RepoProfile``, so attaching a repo is a substitution -- with
  one measured caveat recorded in its docstring: ``resolve_home``'s auto-detection anchors on its
  own file, so a profile carries an ``anchor`` for the checkout it describes.
* :mod:`dev_lab.dev.rules` — the shared registry: one row per UNIVERSAL rule, carrying its
  stable ID, its statement in the words the shared source owns, and the mechanism that refuses a
  violation. A rule with no resolvable mechanism is a REFUSAL in three places -- at construction, so
  prose cannot enter the registry; at adoption, so a repo cannot claim a rule it does not enforce;
  and at check time, so a deleted mechanism reds. ``Adoption`` is what makes the registry SHARED
  rather than merely central: a rule's statement is universal, its mechanism lives in one tree.
* :mod:`dev_lab.dev.hooks` and :mod:`dev_lab.dev.hook_adoption` — the same split one level
  down, for the machinery that REFUSES a command rather than a design: one row per universal denied
  shape, each NAMING ITS REMEDY, and a per-repo adoption that supplies the exit. A rule whose remedy
  does not exist in the adopting repo is not shipped there: a sealed road is routed around, not
  obeyed. :mod:`dev_lab.dev.allow_adoption` is that registry's ALLOW half and closes the seam
  that left those exits unreachable -- ``permissions.allow`` is DERIVED from the remedies a repo
  supplies (three of nine live rows, 2026-09-18), and only a road answering no rule is DECLARED.
* :mod:`dev_lab.dev.units` — the naming half of the units rule: a scan that refuses an
  identifier whose trailing segment spells a unit, because the unit belongs in the VALUE (see
  :func:`lab_commons.units.quantity_parser`). It reports the token set it searched for, so finding
  nothing is distinguishable from searching for nothing.
* :mod:`dev_lab.dev.unit_slices` -- the unit-in-name gap that scan does NOT see, measured as
  named slices (locals, attributes, output keys, Rust identifiers, comment units, absolute
  tolerances) and reported, never a verdict; ``python -m dev_lab.dev.units report <root>``.
* :mod:`dev_lab.dev.cjk` — the family's ONE "no CJK in tracked source" guard (user directive,
  2026-09-16): the scan, the five CJK ranges, the ``.claude/memory/``/``attic/``/``archived/``
  exemptions and the floor are shared; each adopting repo supplies its own named-set declaration of
  files still carrying CJK, exactly the shape the suppression ratchet already uses, so a population
  too large for one commit can be migrated as a ratchet instead of a flat assertion. Re-exported
  below under ``CJK``-prefixed names because :class:`~dev_lab.dev.units.Scan` and
  :func:`~dev_lab.dev.units.scan_files` already own the unqualified spellings.
* :mod:`dev_lab.dev.docwidth` — the family's ONE per-line WIDTH ceiling for every document
  injected into an agent's context (user directive, 2026-09-16): a line-COUNT ratchet is blind to
  how long each line is, so this caps columns too, at 120 -- the ceiling every repo already uses for
  code. The injected-document corpus (``AGENTS.md``/``CLAUDE.md`` by basename, ``.claude/rules/**``,
  ``.claude/memory/`` excluded) is DATA a consumer may override, and the ratchet shape is the same
  named-set declaration as :mod:`dev_lab.dev.cjk`.
* :mod:`dev_lab.dev.principles` — the family's engineering PRINCIPLES, one tuple (user ruling 2026-10-27):
  rendered to ``.claude/rules/principles.md`` by ``hook_install --install`` in every repo (pinned by
  :mod:`dev_lab.dev.famtests.principlespage`), and handed to the review method as ``--principles <json>``.
* :mod:`dev_lab.dev.reviewpolicy` — the family REVIEW POLICY resolved for one repo (``--json [--repo]``),
  read from the values the forge review runs on and exported for both triggers (user ruling D83).
* :mod:`dev_lab.dev.hook_install` — HOOKS-ARE-WIRED, and the half a hook table cannot answer
  for itself: the TOML DECLARES hooks, installing their shims is a separate act on a separate
  machine, and nothing links the two. Measured 2026-09-16: ``consumer-b`` and
  ``consumer-c`` each declared a full configuration and had ZERO hooks installed. It reports and
  never repairs itself -- a hooks directory is shared by every worktree of a checkout -- and its
  refusal names a remedy DERIVED from the configuration rather than restated beside it.
* :mod:`dev_lab.dev.bounded` — REFUSAL-NAMES-THE-REMEDY, all three halves of it: a wall that
  terminates the process TREE (``subprocess.run``'s timeout kills only the direct child and then
  reaps unbounded, which is a hang detector that hangs), the WIDTH a refusal must consult before it
  may call a run a tier boundary rather than a narrowed box, and the sentence itself -- three
  states, three DIFFERENT remedies, two of which are wrong in the other's case.
* :mod:`dev_lab.dev.netverb` - NETWORK-RETRY-THEN-REPORT, the family half of it: a BOUNDED
  retry around a network verb, a classification table saying which failures can clear on another
  attempt (a 401 cleared on a retry; a rejected ref, a 403 and a pre-push hook's refusal repeat
  identically), and a ``Report`` the caller BRANCHES on instead of a printed word "blocked". It
  composes with ``bounded`` for the wall rather than restating it. Reached BY NAME -- as an API,
  and as ``python -m dev_lab.dev.netverb -- git fetch origin`` for a shell caller -- so it is
  not re-exported below, exactly as ``verify`` is not: a package that imports its own entry point
  makes ``runpy`` warn the module was already in ``sys.modules``.
* :mod:`dev_lab.dev.liverun` - TREE-HAS-A-LIVE-RUN: a checkout a live process READS (a Python interpreter
  working in it, or an argument naming a path in it, read off :mod:`lab_commons.census`) refuses
  Edit/Write (its ``hook``) and, through the deny engine's ``when: 'live-run'`` row, merges, checkouts and
  environment syncs; ``dep`` refuses a venv any live process executes from. ``output/``, ``.claude/`` and
  ``.venv/`` are not the tree.
* :mod:`dev_lab.dev.checkout` — SHARED-CHECKOUT, which both siblings declared absent on the
  grounds that the push obligation "is a fact about origin, not about any file in this checkout".
  The premise is true and the conclusion was wrong: git answers "what is here that origin does not
  have" exactly and without a network call. Measured against the REMOTE and never a local pointer,
  and with ``git cherry`` rather than ancestry, because those are the two ways this audit has
  actually been observed to lie.
* :mod:`dev_lab.dev.filechecks` -- the base pre-commit rows' per-file checks (stdlib, report and
  never rewrite).
* :mod:`dev_lab.dev.ciworkflows` -- GitHub workflows declared in TOML (``ci_base.toml`` plus
  ``[tool.dev_lab.ci]``) and rendered to ``.github/workflows``; ``check`` refuses a hand edit.
* :mod:`dev_lab.dev.githooks` -- the TOML hook table, its one runner (``python -m
  dev_lab.dev.githooks run <stage>``), and the hook SCRIPTS shipped as a package payload and
  reached by NAME (``... githooks script bump-version``). They are not all hooks: ``with-venv`` is a
  WRAPPER that takes the
  command to run as arguments, and ``git-env-repair`` is a FRAGMENT that is SOURCED -- running one
  exits 0 having done nothing, which reads exactly like a hook that passed, so ``KINDS`` declares
  what each is and ``run_hook`` refuses the fragment. A repo fact a script cannot derive arrives as
  an environment variable with NO DEFAULT (``LAB_CZ_BASE_REF``, passed by a hook row`s ``env``), the
  shape :mod:`~dev_lab.dev.dep` already uses. Not re-exported below: it is run, not imported.
* :mod:`dev_lab.dev.agenthooks` -- the agent-guard ENGINE itself, shipped as a package payload
  the way ``githooks`` ships its scripts, and JavaScript because a ``PreToolUse`` hook is a command
  whose stdout is a JSON decision. It MOVES verbatim: two answers to "what will this shell line
  execute" is the fork these modules exist to remove. Unlike a git hook it is INSTALLED into the
  consumer, its command line in a committed ``.claude/settings.json``.
* :mod:`dev_lab.dev.agent_guard` -- AGENT-GUARD-IS-LIVE, the hook-install question one layer up:
  a rendered ``deny-rules.json`` is a DECLARATION, and installing the engine plus its ``PreToolUse``
  wiring is a separate act. MEASURED 2026-09-17: the registry and its wiring recipe existed while the
  engine lived in ONE repo of four, so rendering rules anywhere else would have produced an inert
  declaration that reads as a guard. Three parts reported BY NAME -- engine, rules, wiring -- because
  each fails differently, and installing is an EXPLICIT request that never clobbers an unrelated
  setting, matcher, or an engine lab-commons did not ship. Not re-exported below.
* :mod:`dev_lab.dev.docsite` -- the documentation-site driver: a TABLE of sub-sites, every
  subprocess checked and bounded, and a missing toolchain that SKIPS and SAYS SO on the portal page
  rather than failing the build or vanishing from it. Not re-exported below.
* :mod:`dev_lab.dev.quantity_values` -- the VALUE half of the units rule, and the reason it is a
  second module rather than a wider ``units``: a scan that refuses a unit-spelling NAME rewards the
  LOSSY repair -- deleting the suffix silences it and records the unit nowhere. This proves the unit
  reached the VALUE instead, and ``migration_conflicts`` refuses a key in both waiver and registry.
* :mod:`dev_lab.dev.verifybox` -- the verify door's box claim: a selection's pytest step runs in the
  box at a declared, enforced demand; a producer serve spawned is not boxed twice.
* :mod:`dev_lab.dev.serialpass` -- the family's ``serial`` marker: a marked test runs alone in verify's
  single-worker stage after the parallel one.
* :mod:`dev_lab.dev.inflight` -- one run per ``(tree, env, selector)`` on the box: a duplicate
  request ATTACHES to the run in flight and receives its answer instead of running the suite again.
* :mod:`dev_lab.dev.lockwait` -- verify's ``--lock-wait``: a duration quantity, a bare number refused.
* :mod:`dev_lab.dev.lockpins` -- a git-installed package whose commit differs from the checkout's
  ``uv.lock`` makes an env STALE; verify refuses it naming the sync door. Never judged against a remote tip.
* :mod:`dev_lab.dev.selection` -- what a verify argv selects: targeted or the whole suite, and
  whether it may claim the skip census.
* :mod:`dev_lab.dev.forgeserve` -- ``forge serve``: the one harness entry (tick, produce,
  publish, route); a producer refusing its argv is a broken contract, never a skip.
* :mod:`dev_lab.dev.forgeservesteps` -- the contained steps after a serve tick: issue alarms, hygiene, retention.
* :mod:`dev_lab.dev.forgeproduce` -- one local part produced inline: streamed, claim held, released if left pending.
* :mod:`dev_lab.dev.forgeintent` -- a local run's claim journaled before it runs; a restart re-attaches to it.
* :mod:`dev_lab.dev.forgerounds` -- serve's rounds: claim while producing, each live producer running.
* :mod:`dev_lab.dev.forgecarry` -- REACH-CARRY: an outcome stands at a descendant whose diff misses its
  test's footprint; per outcome on a cluster run, per part when every test carries.
* :mod:`dev_lab.dev.footprint` -- the repo paths a test file's outcome can depend on, derived statically.
* :mod:`dev_lab.dev.localpart` -- a local run as a ``tests/<part>`` part, in the cluster
  record's shape.
* :mod:`dev_lab.dev.jobparts` -- the same parts produced by workflow jobs: the matrix of parts and runners,
  one producer per part, and ``absent`` for every part no job settled.
* :mod:`dev_lab.dev.commandpart` -- a repo whose tests are not pytest (``npm test``) posts its part as ONE
  cell, the command, judged by its exit code.
* :mod:`dev_lab.dev.runcache` -- this box's cache of judged verify runs, keyed by tree, env and
  selector: a judged key is cited, not re-run. It decides no push.
* :mod:`dev_lab.dev.test_outcomes` -- the pytest plugin writing a Record of per-test cells
  (:mod:`lab_commons.outcomes`) per process, so a local run posts the same kind of part a cluster run does.
* :mod:`dev_lab.dev.lockcheck` -- the PIN reading (half of PIN + FRESHNESS): a commit commits ``uv.lock`` and
  every hold below the newest declares its reason; judged on the forge by ``famtests.lockpin``, relocked by ``relock``.
* :mod:`dev_lab.dev.relock` -- the serve tick relocks a stale integration lock through ONE pull request.
* :mod:`dev_lab.dev.forgeheadgate` -- ``lock/fresh`` and ``branchset`` statuses on every open PR head,
  each naming its fix.
* :mod:`dev_lab.dev.lanepolicy` -- the branch names a repo declares in
  ``[tool.dev_lab.integrator]``, read by the queue, admission, the tick and the record attacher.
* :mod:`dev_lab.dev.platformparts` -- a result COMPOSED of one part per need-set the suite derives
  (``base``, ``jmag``, ``femm+windows``...), each a ``tests/<part>`` status on the forge.
* :mod:`dev_lab.dev.partrows` -- the name of an OS-qualified part row (``base@windows``): its part, its
  system, and this machine's platform.
* :mod:`dev_lab.dev.producer` -- the producer exit contract: what a part producer's exit code
  means to ``forge serve`` (PASS, FAIL, refused argv, INCONCLUSIVE, UNREACHABLE), one source.
* :mod:`dev_lab.dev.dep` -- the family's ONE door for mutating a Python environment, decided by
  STATE rather than by command TEXT: no verdict may cite an environment it did not run in, so a
  mutation DURING a run is PREVENTED against the box lock and a mutation BETWEEN runs RETIRES the
  stored anchors. It reads ``sys.prefix`` of the invoking interpreter, which is what makes the
  sibling-repo false positive structurally impossible rather than merely fixed.
* :mod:`dev_lab.dev.installdoor` -- the OTHER half of ``dep``'s invariant: ``dep`` decides WHEN
  an environment may move, this whether a path that moves one delivers the DECLARED build of a
  requirement carrying no ref -- MEASURED per tool, not read off a flag name, which is why the
  reverting door found here was a git hook and not a Makefile target.
* :mod:`dev_lab.dev.doorcensus` -- the question above it, which no per-repo guard can answer
  about itself: **was this repo's door set ever looked at, and is it still what was measured?** One
  row per repo per door by EQUALITY, not a floor; plus DECLINED rows, so a door left out is
  distinguishable from one nobody looked at, and SHARED rows, stored in one repo and RUN in others.
* :mod:`dev_lab.dev.syncscope` -- the OTHER half of what a sync does, which the two above are
  blind to by construction: they judge the BUILD one distribution arrives at, this the POPULATION
  left behind, after ``uv sync`` with no ``--extra`` took a box from 113 to 30 distributions while
  delivering the declared build. A tree with no pytest reads as BROKEN, not as UNEQUIPPED, and the
  answer is a JOIN never a property of the command: ``--extra all`` means whatever that repo's own
  manifest says, which in consumer-a is six extras and neither ``dev`` nor ``img-to-cad``.
* :mod:`dev_lab.dev.collectscope` -- the half ``syncscope`` names as UNMEASURABLE in its own
  docstring, which needs a second text to answer: the TEST TREE. A scope that scored COMPLETE still
  leaves a repo with NO VERDICT when a module-scope import is gone, because pytest IMPORTS what it
  collects and a collection error judges nothing. The join is IMPORT name to DISTRIBUTION name and
  they differ; reading that from installed metadata was measured and REFUSED, since an already-pruned
  environment answers that a distribution does not exist. A guard DEGRADES and a skip mark does not.
* :mod:`dev_lab.dev.synccensus` -- that reader pointed at the selections the family makes, which
  are mostly in a different repo from the command that syncs: one shared CI workflow builds its
  extras from each caller's ``extras:`` line. EQUALITY on scope and on the stranded set, plus a
  DERIVED scan refusing a pruning command no row accounts for. Not re-exported below.
* :mod:`dev_lab.dev.collectcensus` -- ``collectscope`` pointed at the selections a repo makes:
  one row per (repo, selection) recording what its test tree would strand, degrade or leave
  unresolved, by EQUALITY both ways, plus the audit refusing a residue name the manifest already
  answers. The kit holds only its own row; each consumer declares its rows and calls
  ``assert_reaches`` over its own checkout. Not re-exported below.
* :mod:`dev_lab.dev.ruffwaivers` -- the two ruff waivers WIDER than an ignore, ``exclude`` and
  ``per-file-ignores``, read across every spelling ruff honours from the config ruff RESOLVES, and
  ``assert_waivers_declared``, which refuses an undeclared waiver and a stale row alike. A repo
  declares its own rows; the kit ships the reader and the refusal. Not re-exported below.
* :mod:`dev_lab.dev.privatemarkers` -- the scan a PUBLISHED repo runs over every tracked file:
  generic patterns (home paths, non-reserved e-mails, chat ids, cloud folder names) plus an optional
  machine-local denylist reported by kind only. Each consumer calls ``scan_tree`` over its own
  checkout from one test. Not re-exported below.
* :mod:`dev_lab.dev.security` -- the three scans a head passes before a merge: ruff ``S`` under the
  family's declared ignores, a tracked-credential scan reported by digest only, and the ``uv.lock`` pins
  against OSV. Not re-exported below.
* :mod:`dev_lab.dev.ephemeralrefs` -- TRACKED-CITES-NO-EPHEMERAL: no tracked file cites what git
  ignores, nothing untracked under a stray root (``scratch/``), and no machine-local path. Not re-exported below.
* :mod:`dev_lab.dev.devdocs` -- the family's MECHANISM DOCS as DATA: one row per page under this
  repo's ``docs-src/dev/``, with the pointer table a consuming repo RENDERS instead of copying. The
  prose itself is deliberately NOT here -- ``tests/test_arch_rules_pages.py`` refuses markdown under
  ``src/`` -- so what ships is the table of contents, which is the half that rots when four repos
  hand-maintain it. Not re-exported below.
* :mod:`dev_lab.dev.envseat` -- one canonical environment seat shared by verdicts and mutations,
  independent of the box CPU seat. Not re-exported below.
* :mod:`dev_lab.dev.shadow_build` -- measuring a rebuilt native extension WITHOUT installing it.
  Each worktree owns its venv; ``maturin develop`` still mutates the interpreter a verdict may be
  running in -- the :mod:`~dev_lab.dev.dep` hazard arriving through a build tool, which takes no
  lock and asks nobody. So it BUILDS a wheel, UNPACKS it (a wheel is a zip) and SHADOWS the
  installed copy via ``PYTHONPATH``, refusing any output path inside ``sys.prefix``; and it times
  the two arms A/B/A/B, because a block design charges a shared box's drift to whichever arm ran
  during it. It reports a KERNEL ratio and deliberately carries no end-to-end figure: the weight
  that would produce one is a property of the consuming repo's cases. Not re-exported below.
* :mod:`dev_lab.dev.ab_bench` -- the other half of that measurement: an IN-PROCESS seam, where
  its sibling times CHILD PROCESSES. The difference is the failure modes, not the scale. There may
  be more than two arms; an arm may legitimately REFUSE an input its rivals accept, which is an
  ANSWER and is recorded rather than aborted on; and an arm may pay a one-time setup, which is
  amortised over a recurrence count the CALLER measured, never over 1 and never over 0. A refused
  arm reports no median at all, because a candidate timed only on the inputs it accepted has
  selected its own sample. Whether a seam can be DISPATCHED on at all is asked rather than assumed,
  and the pairs that forbid it are named. NOT RE-EXPORTED.
* :mod:`dev_lab.dev.testfacts` -- what a test FILE declares about itself, and one assertion
  SHAPE (a test whose assertions are ALL ``is not None``, which cannot fail behaviourally), read from
  the AST and never by collecting: collection IMPORTS, and a census that collects starts MATLAB to
  find out whether a test starts MATLAB. Marks, ``timeout`` literals, ``test_``-prefixed functions
  and that shape are facts about PYTEST and are shared; which marks name a vendor, which paths a tier
  claims and what its wall is arrive as PREDICATES the consumer supplies. The partition is
  first-match-wins with a REQUIRED residual bucket, because the population that matched nothing -- in
  a slow tier for no reason any code can read -- is the reading the whole instrument exists for. Not
  re-exported below: ``collect`` and ``census`` say nothing about their subject once flattened.
* :mod:`dev_lab.dev.selfbuild` -- the one environment mutation that is NOT a dependency change:
  installing a wheel this workspace built from the checkout you are standing in. It composes with
  :mod:`~dev_lab.dev.dep` rather than repeating it -- that door decides WHEN an environment may
  move, this one decides WHOSE wheel may go through it in :attr:`~dev_lab.dev.dep.Mode.PINNED`.
  Without the ownership half, ``--no-index`` is a safety catch on a loaded gun: it stops an index
  being read and says nothing at all about ``pip install ./somebody-elses.whl``. The set of
  distributions a workspace builds is READ from the manifests the caller hands in, never spelled in a
  guard, and an empty set refuses everything rather than comparing vacuously. Not re-exported below.
* :mod:`dev_lab.dev.famconfig` -- the family's CONFIG artefacts as one BASE plus a named DELTA,
  rendered, with a guard that reds on a hand edit rather than letting it drift. A consumer therefore
  has two states and no third: it reads the family artefact, or it declares its delta. The measured
  counts, why a DROP is a mapping-to-its-reason and never a set, why an addition may be ANCHORED
  inside a rendered block, why ``REQUIRED`` exists beside ``RENDERED``, and why `[tool.ruff]` is
  deliberately absent are all in that module's own docstring. Not re-exported below.

R4 PHASE 1, THE ``scripts/gate/`` AND ``scripts/repo/`` MECHANISMS (2026-09-17) -- eight modules,
family half only, no consumer re-pointed, none re-exported. ONE LINE EACH AND THE BREVITY IS FORCED: this file entered
the tranche at 387 lines against a 400-line band, so the reasoning stays in each module's own
docstring rather than being copied here -- and the NEXT module to arrive must split this inventory.

* :mod:`dev_lab.dev.codeplace` -- code under DECLARED roots; no stray file.
* :mod:`dev_lab.dev.scratch` -- scratch is visible to git, never committed; a one-off is promoted or deleted.
* :mod:`dev_lab.dev.reportplace` -- no agent-written Markdown under ``output/``; a written report is a memory entry.
* :mod:`dev_lab.dev.datedlog` -- one dated log layout; the base has NO DEFAULT (four repos, four answers).
* :mod:`dev_lab.dev.shards` -- a partition, the AND over a shard set, and a required population FLOOR.
* :mod:`dev_lab.dev.bypath` -- a by-path load as a CALL: one object per FILE, nothing to suppress.
* :mod:`dev_lab.dev.seams` -- rebinding for measurement WITH the undo; an unresolved seam is reported.
* :mod:`dev_lab.dev.gatebase` -- the NARROWEST admitted ancestor of HEAD; refs arrive with NO DEFAULT.
* :mod:`dev_lab.dev.treedirt` -- did the tree MOVE while judged; identity stays with ``content``.
* :mod:`dev_lab.dev.symcov` -- public symbols of one tree found in another; the floor is REQUIRED.
* :mod:`dev_lab.dev.forge` -- branch protection against a DECLARATION; INERT is its own standing.
* :mod:`dev_lab.dev.forgework` -- issue/PR verbs over Gitea/GitHub REST, no ``gh``/``tea``; ``HARNESS_*`` stamp.
* :mod:`dev_lab.dev.forgelabels` -- labels by NAME on both forges: resolved to ids, created, put on an issue.
* :mod:`dev_lab.dev.forgepublish` -- ``forge request``: publish a request only when a host could reproduce it.
* :mod:`dev_lab.dev.forgestatus` -- a verdict PUBLISHED as a commit status (INCONCLUSIVE: ``error``).
* :mod:`dev_lab.dev.forgewatch` -- ``forge watch <sha>``: read-only, a commit's verdicts until settled or a deadline.
* :mod:`dev_lab.dev.forgestuck` -- STUCK-RUN-CANCEL: ``forge cancel-stuck <sha>`` scancels only its stuck forge tasks.
* :mod:`dev_lab.dev.forgeoutbox` -- a status KEPT until its commit is on origin, then posted with its record.
* :mod:`dev_lab.dev.forgerecords` -- run records as cleanable forge attachments; ``records prune``.
* :mod:`dev_lab.dev.forgeunit` -- compute units on the forge: shared results (first wins), a unit offered as a Job.
* :mod:`dev_lab.dev.forgeorigin` -- the commit-msg ``Forge-Host:`` stamp a ``[priority] hosts`` entry matches.
* :mod:`dev_lab.dev.forgetake` -- the claim pass of a tick: each ranked candidate claimed while it admits.
* :mod:`dev_lab.dev.forgerequest` -- a request: an issue-declared job ranked, admitted and run on the part path.
* :mod:`dev_lab.dev.forgetick` -- requests derived from origin; the best feasible one claimed each tick.
* :mod:`dev_lab.dev.forgecred` -- how a stored secret (:mod:`lab_commons.credentials`) meets a forge.
* :mod:`dev_lab.dev.forgedemand` -- SHARED DEMAND: the forge's run records folded into the learned cache.
* :mod:`dev_lab.dev.forgeclaim` -- a claim is a pending status with a lease; the earliest wins the race.
* :mod:`dev_lab.dev.forgecoalesce` -- one run per coalesced ref and part in flight; the tip waits behind it.
* :mod:`dev_lab.dev.forgeschedule` -- ONE derived work queue: value per cost, aging, budgets, starvation.
* :mod:`dev_lab.dev.forgequeue` -- ``forge queue``: queue, runs in flight, hosts and starvation, from the forge.
* :mod:`dev_lab.dev.forgehosts` -- one host card per serving host, edited in place on the forge.
* :mod:`dev_lab.dev.forgepoller` -- ONE POLLER PER REPO: a lease on the hosts issue picks the host that polls.
* :mod:`dev_lab.dev.forgesettled` -- a commit whose every part is settled is read once, its history kept.
* :mod:`dev_lab.dev.forgeprovides` -- what a host provides (machine-file ``[capabilities]``); no live host
  having a part's need-set is named.
* :mod:`dev_lab.dev.forgetidy` -- ``forge tidy``: issues never rot: finished, idle and retired-marker leftovers go.
* :mod:`dev_lab.dev.forgerun` -- a cluster part as a resumable tick: on-disk run state advanced per serve call.
* :mod:`dev_lab.dev.forgerunpost` -- a cluster run's forge posts (progress, release), saved steps and alarms.
* :mod:`dev_lab.dev.forgerunstate` -- a cluster run's state file, its schema upgrades, and the Slurm protocol.
* :mod:`dev_lab.dev.components` -- the engines a product mounts under ``components/``, declared once.
* :mod:`dev_lab.dev.componentbump` -- one forge-green engine commit at a time becomes a one-pointer lane.
* :mod:`dev_lab.dev.shatree` -- a local part judged in a tree AT the claimed sha, its own env, removed after.
* :mod:`dev_lab.dev.forgeoom` -- an OOM-killed task floors every file it ran at its ask, in the folded record.
* :mod:`dev_lab.dev.forgeslurm` -- the Slurm side of a cluster run, and the account's standing read locally.
* :mod:`dev_lab.dev.forgeship` -- a cluster run's declared outputs stored on the serve path, and the
  store cleanup its host owns.
* :mod:`dev_lab.dev.retention` -- the storage retention pass serve runs every tick, and its quota alarm.
* :mod:`dev_lab.dev.retentionplan` -- what retention deletes: a tree or env once nothing in flight needs it.
* :mod:`dev_lab.dev.diskusage` -- an account's quota (`mmlsquota`) or a disk's usage, and what one path holds.
* :mod:`dev_lab.dev.artefacts` -- the artefact store: declared outputs packed once, the backend
  chosen by size, one shared library whose every writer cleans only its own runs.
* :mod:`dev_lab.dev.artefactstores` -- the run-id and key rules, the ``Ref``, and the forge and
  rclone backends.
* :mod:`dev_lab.dev.forgeaffinity` -- HPC account affinity: verify accounts claim a verify part first.
* :mod:`dev_lab.dev.forgealarm` -- silent failures of an unattended host as one routed line and alerts.
* :mod:`dev_lab.dev.forgefleet` -- a platform with no live host, or a tick serving nothing, alarms once per episode.
* :mod:`dev_lab.dev.hostalarm` -- D54: a host pressed for disk/memory/CPU tells its agents (hook) and humans.
* :mod:`dev_lab.dev.pushgate` -- PUSH ADMISSION: lanes and integration free, the trunk every forge part green.
* :mod:`dev_lab.dev.forgeissue` -- issue state DERIVED from origin refs and the lane parts; claims, comment reads.
* :mod:`dev_lab.dev.forgeroute` -- a run record's reds grouped by ``[tool.dev_lab.areas]``, one issue per area.
* :mod:`dev_lab.dev.integrator` -- the merge queue DERIVED from origin refs and the tests/<part> parts.
* :mod:`dev_lab.dev.trialmerge` -- what a merge WOULD do (behind, conflicts) from objects alone, no checkout.
* :mod:`dev_lab.dev.forgepulls` -- PR list/retarget, ONE marker-found comment per subject, the incremental issue
  read, both forges.
* :mod:`dev_lab.dev.integrate` -- integration by refs alone: ``merge <branch>`` (merge-tree, the commit-msg
  stage and the merge audit, compare-and-swap) and ``promote <sha>`` (the local trunk FAST-FORWARDS to a
  full-PASS integration commit). Neither checks out nor pushes.
* :mod:`dev_lab.dev.forgesync` -- ``forge sync``: a child merges integration, plus only the refs it watches.
* :mod:`dev_lab.dev.forgeintegration` -- ``forge integration``: per child branch, one comment or status.
* :mod:`dev_lab.dev.forgemerge` -- the forge's server-side merge of a reviewed, clean PR into integration.
* :mod:`dev_lab.dev.forgeautosync` -- the serve tick merges integration into a behind ``pr/*`` PR head.
* :mod:`dev_lab.dev.forgenotice` -- ``forge notices``: a red, conflicting or stalled PR head, told to its sessions.
* :mod:`dev_lab.dev.forgetry` -- ``forge try <paths>``: named tests on a host with room now, or ``no room`` at once.
* :mod:`dev_lab.dev.forgewait` -- a part's wait answered, bounded and seen: why a box does not admit it, until when.
* :mod:`dev_lab.dev.forgecontexts` -- the status contexts under ``tests/``: the part prefix, and those never a part.
* :mod:`dev_lab.dev.forgesecurity` -- ``tests/security``, one status per head from a serve step; a merge condition.
* :mod:`dev_lab.dev.forgereview` -- the review of each open PR head by the declared command; HIGH/security block.
* :mod:`dev_lab.dev.forgereview_claim` -- a head's review claim: who may take it, what stands on it, a host unable.
* :mod:`dev_lab.dev.forgereview_command` -- whether this host can start the review command, and running it.
* :mod:`dev_lab.dev.forgereview_findings` -- the findings JSON that command prints, read at a known version only.
* :mod:`dev_lab.dev.forgereview_rounds` -- review rounds: findings carried by stable id, re-judged each round.
* :mod:`dev_lab.dev.reviewbudget` -- a PR's review capped in rounds and USD inside the family's month, fitted.
* :mod:`dev_lab.dev.forgereview_dispose` -- ``forge review dispose`` records a claim; ``adjudicate`` rules on it.
* :mod:`dev_lab.dev.forgereview_judge` -- every round re-judges each open finding; a claim is adjudicated
  by an independent reviewer, never the head's author session.
* :mod:`dev_lab.dev.reviewgate` -- the ONE predicate of a reviewed head, for the merge and Break-Glass.
* :mod:`dev_lab.dev.forgetakeover` -- ``forge review takeover``: an ADVISORY session review; never the gate (D11).
* :mod:`dev_lab.dev.forgereview_scope` -- what a review reads: the own change, minus generated files, in lens slices.
* :mod:`dev_lab.dev.forgereview_runtimes` -- where this host keeps a review command's interpreters (``[runtimes]``).
* :mod:`dev_lab.dev.metrics` -- the toolchain's baseline: refusals and hand actions, one JSONL per kind (record).
* :mod:`dev_lab.dev.metrics_compute` -- the plan's figures from the recorded lines, forge pulls and git landings.
* :mod:`dev_lab.dev.metrics_report` -- the family's metrics over one window, and the metrics CLI.
* :mod:`dev_lab.dev.mergeaudit` -- a merge may not lose or rewrite a test in silence: the three-way audit at commit.
* :mod:`dev_lab.dev.mergeresolution` -- a conflicted merge names, per conflicted file, how it was resolved and why.
* :mod:`dev_lab.dev.labsession` -- the launcher's ``LAB_SESSION`` stamped as ``Lab-Session`` at commit-msg.
* :mod:`dev_lab.dev.pradmit` -- PR advice: ONE-SESSION-ONE-PR and NO-STACKED-PRS told at ``pr create``, never a refusal.
* :mod:`dev_lab.dev.issueref` -- the commit-msg check: WARNS on a malformed ``Refs #N``, never blocks.
* :mod:`dev_lab.dev.forgecli` -- the ``python -m dev_lab.dev.forge`` noun dispatch over the ``forge*`` doors.
* :mod:`dev_lab.dev.forgeauth` -- ``auth login|status``: a token VERIFIED, then stored by ``git credential``.
* :mod:`dev_lab.dev.floors` -- a scan that read NOTHING is not a clean scan; both sides, no default.
* :mod:`dev_lab.dev.foreign` -- the leaf's own tier-1 rule, made refusable: which string
  constants here name a SIBLING or a path this checkout cannot resolve. Three kinds, because they
  are not equally wrong -- executable DATA, a consumer TREE PATH, and PROSE -- and the waiver is a
  NAMED SET of evicted-by-design rows rather than a count, so a deletion lands mechanically. NOT
  RE-EXPORTED -- ``scan`` and ``kinds`` say nothing once flattened.
* :mod:`dev_lab.dev.disclosure` -- INJECTED-TEXT-IS-PROGRESSIVE: the injected-text budgets and the details pointer.
* :mod:`dev_lab.dev.family` -- who is in the family: a checkout whose own ``pyproject.toml`` declares
  ``[tool.dev_lab]`` or ``[tool.lab_commons]``; :func:`~dev_lab.dev.family.declared_table` reads dev-lab's own tables.
* :mod:`dev_lab.dev.breakglass` -- the one emergency bypass of INTEGRATION-TAKES-ONLY-FORGE-MERGES: a
  ``Break-Glass: <reason>`` trailer on every new commit, kept visible as an ``integration`` issue.
* :mod:`dev_lab.dev.branchset` -- ONE-BRANCH-PER-SESSION: the DECLARED branch set, and what to merge or delete.
* :mod:`dev_lab.dev.refspec` -- git's pre-push refspec lines, parsed once for every pre-push row that reads them.
* :mod:`dev_lab.dev.branchnotices` -- FORGE NOTICES where a session acts on its PR (post-commit, pre-push,
  ``pr create``): that PR's open notices for the session, cached, read-only, bounded; never fails the verb.
* :mod:`dev_lab.dev.sessionbranch` -- the pre-push guard of every declared session branch, local reads
  only: publish = the local ref, history only grows, integration takes merges only.
* :mod:`dev_lab.dev.branchprune` -- MERGED-BRANCHES-PRUNED: every serving host deletes merged idle origin
  branches when the repo opts in, lists them when it does not, and alarms unmerged stale ones; it is the
  command line of ``delete`` and ``sweep``, and a workstation's ``PostToolUse`` hook detaches ``sweep --local``.
* :mod:`dev_lab.dev.branchdelete` -- LOSSLESS-DELETE and LANDED-BRANCHES-SWEPT: a branch is deleted only when
  its content is held elsewhere; ``sweep`` deletes every branch integration now contains (ancestry or content),
  after each integration move: the serve pass, GitHub's push job, and the ``PostToolUse`` hook.
* :mod:`dev_lab.dev.prlanded` -- LANDED-PRS-CLOSE: an open PR whose head is on its base is commented and closed,
  its branch left to the prune; every serve tick, and ``forge pr close-landed``.
* :mod:`dev_lab.dev.prsuperseded` -- SUPERSEDED-PRS-CLOSE: ``forge pr close-superseded <n>... --by <pr|sha>``
  closes salvaged PRs with an evidence comment; it never deletes a branch.
* :mod:`dev_lab.dev.forgescarce` -- SCARCE-PARTS-BY-REACH: a scarce part runs on a PR only where its diff reaches it.
* :mod:`dev_lab.dev.unproduced` -- a resource a repo declares no part for: every reading waives it.
* :mod:`dev_lab.dev.autodoors` -- AUTO-MODE-RUNS-THE-DOORS: one door table, rendered for Claude and Codex.
* :mod:`dev_lab.dev.automode` -- REPO-AUTOMODE: the machine-local, gitignored auto-mode prose, derived per machine.
* :mod:`dev_lab.dev.worktrees` -- the local worktree door: reclaim clean, landed, unoccupied trees; list the rest.
* :mod:`dev_lab.dev.reclaim` -- WORKTREE LEASES: a tree goes once its content is landed and it holds nothing else.
* :mod:`dev_lab.dev.reclaimrun` -- reclaim as a SessionStart step: detached, locked, a bounded batch, never blocks.
* :mod:`dev_lab.dev.worktree_archive` -- `--archive NAME`: outputs move home, work is saved, nothing removed.
* :mod:`dev_lab.dev.stoprun` -- the stop-own-run door: one identifiable gate/verify/serve tree, children first.
* :mod:`dev_lab.dev.handback` -- the Stop hook: a turn handing the user a runnable command is sent back to the agent.
* :mod:`dev_lab.dev.pushwatch` -- PUSHED-HEAD-IS-WATCHED: the command to arm as a Monitor after a push, and an
  advisory ``PostToolUse`` reminder when a pushed head has no live ``forge watch``.
* :mod:`dev_lab.dev.servelanes` -- one serve lane per repo, so one busy repo never starves the others.
* :mod:`dev_lab.dev.servelock` -- one ``forge serve`` per host: a non-blocking lock, and stopped-producer notes.
* :mod:`dev_lab.dev.servetask` -- the ONE ``lab-forge-serve`` Scheduled Task: its windowless definition and log.
* :mod:`dev_lab.dev.workstation` -- a Windows workstation as a serve host in one run, and the Task's serve loop.
* :mod:`dev_lab.dev.workstationfile` -- the machine-file tables a workstation deploy writes, and its roles.
* :mod:`dev_lab.dev.hpchost` -- a cluster account as a serve host: its deploy, cron tick and allocation record.
* :mod:`dev_lab.dev.hostrefresh` -- the host fast-forwards a served checkout and syncs its venv before its forge.
* :mod:`dev_lab.dev.worktreeplace` -- WORKTREES-STAY-INSIDE: where every checkout lives, and the trees that do not.
* :mod:`dev_lab.dev.famfiles` -- PROJECT-FILES-HAVE-ONE-SOURCE: the one list of project files and the one render.
* :mod:`dev_lab.dev.venvpath` -- the one place that spells a venv interpreter: concrete to run, globbed to track.
* :mod:`dev_lab.dev.durations` -- what every test COST, as a ledger the runner merges rather than
  overwrites, and the two readings a ``slow`` marker set is judged by. The wall's own kills arrive
  at ~0.0s, so they are filed at the WALL: a naive reading acquits exactly what the wall caught.
  NOT RE-EXPORTED -- ``read``, ``write`` and ``over`` say nothing once flattened.
* :mod:`dev_lab.dev.famtests` -- the shared test BODIES a consumer parametrizes; no fact has a default.
* :mod:`dev_lab.dev.jsrun` -- the family's one JS test runtime: a program on stdin under the locked Node.
* :mod:`dev_lab.dev.supersede` -- has the family ALREADY expressed this roster row; overlap GRADES, never detects.

LATEST-DEPENDENCIES, THE RESOLVED HALF (2026-09-21) -- two modules, split where the NETWORK is, so
"a verdict reaches no network" is an import graph rather than a promise in a docstring.

* :mod:`dev_lab.dev.depversions` -- what a checkout RESOLVED: the lock, the live observation, the environment.
* :mod:`dev_lab.dev.dep_observe` -- the refresher, the ONE module here that calls out at all.

THE THREE ROWS THAT CLOSE A RULE ARE NOT RE-EXPORTED BELOW, and that is deliberate rather than an omission: each carries
short status constants whose meaning is local to its own question (``ABSENT``, ``PROTECTED``), and
flattening them into one namespace beside :data:`dev_lab.dev.content.ABSENT` would leave a
reader guessing which of two unrelated answers they are holding. Import them by module.

NOR ARE THE MODULES THAT NEED AN EXTRA: :mod:`~dev_lab.dev.profile`, :mod:`~dev_lab.dev.rules`,
:mod:`~dev_lab.dev.reports` and :mod:`~dev_lab.dev.quantity_values` reach ``platformdirs``, ``rtoml`` or
``pint``. Every submodule import runs this file first, so re-exporting them here would make the stdlib-only
hook runner (:mod:`dev_lab.dev.githooks`) fail in an environment installed without extras.
Import them by module.

WHAT IS DELIBERATELY NOT HERE YET: the five architecture mechanisms (public-surface declaration,
suppression ratchet, module-size alarm, enforced-mechanism registry, duplication ratchet). They take
a ``RepoProfile`` and are the next layer. :mod:`dev_lab.dev.rules` is NOT that layer: it resolves
whether a named mechanism is still LIVE, and the five are the mechanisms an adopter would name.
"""

from dev_lab.dev._unit_tokens import EXCLUDED_TOKENS, UNIT_TOKENS
from dev_lab.dev.cjk import CJK_RANGES, EXEMPT_PREFIXES
from dev_lab.dev.cjk import Occurrence as CJKOccurrence
from dev_lab.dev.cjk import Scan as CJKScan
from dev_lab.dev.cjk import VacuousScan as VacuousCJKScan
from dev_lab.dev.cjk import assert_floor as assert_cjk_floor
from dev_lab.dev.cjk import ratchet as cjk_ratchet
from dev_lab.dev.cjk import scan_files as scan_cjk_files
from dev_lab.dev.content import ABSENT, DEFAULT_IGNORES, content_address, file_digest
from dev_lab.dev.docwidth import (
    INJECTED_BASENAMES,
    INJECTED_EXEMPT_PREFIXES,
    INJECTED_PREFIXES,
    WIDTH_CEILING,
    Overwidth,
    VacuousWidthScan,
    WidthScan,
    assert_width_floor,
    injected_docs,
    is_injected_doc,
    line_widths,
    scan_widths,
    width_ratchet,
    width_remedy,
)
from dev_lab.dev.hook_adoption import HookAdoption, assert_shippable, deny_rules, render, unremedied
from dev_lab.dev.hooks import DENY_RULES, DenyRule, Remedy, UnremediedRule, denies, fires
from dev_lab.dev.logref import MARKER, Citation, LogRef, UnverifiableLog, stamp_line, verify_log
from dev_lab.dev.units import (
    SCANNED_SUFFIXES,
    Scan,
    Violation,
    assert_registry_sane,
    scan_files,
    trailing_token,
)
from dev_lab.dev.verdict import IncompleteRun, Proof, Result, Selector, Verdict

__all__ = [
    'ABSENT',
    'CJK_RANGES',
    'DEFAULT_IGNORES',
    'DENY_RULES',
    'EXCLUDED_TOKENS',
    'EXEMPT_PREFIXES',
    'INJECTED_BASENAMES',
    'INJECTED_EXEMPT_PREFIXES',
    'INJECTED_PREFIXES',
    'MARKER',
    'SCANNED_SUFFIXES',
    'UNIT_TOKENS',
    'WIDTH_CEILING',
    'CJKOccurrence',
    'CJKScan',
    'Citation',
    'DenyRule',
    'HookAdoption',
    'IncompleteRun',
    'LogRef',
    'Overwidth',
    'Proof',
    'Remedy',
    'Result',
    'Scan',
    'Selector',
    'UnremediedRule',
    'UnverifiableLog',
    'VacuousCJKScan',
    'VacuousWidthScan',
    'Verdict',
    'Violation',
    'WidthScan',
    'assert_cjk_floor',
    'assert_registry_sane',
    'assert_shippable',
    'assert_width_floor',
    'cjk_ratchet',
    'content_address',
    'denies',
    'deny_rules',
    'file_digest',
    'fires',
    'injected_docs',
    'is_injected_doc',
    'line_widths',
    'render',
    'scan_cjk_files',
    'scan_files',
    'scan_widths',
    'stamp_line',
    'trailing_token',
    'unremedied',
    'verify_log',
    'width_ratchet',
    'width_remedy',
]
