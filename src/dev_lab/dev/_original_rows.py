"""THE `dev_lab.dev` MODULES WITH NO CONSUMER FORK BEHIND THEM -- DATA, one name per module.

The `original` half of the provenance registry. `_provenance_rows.py` holds the rows that make a
CLAIM about a consumer file (`supersedes`, `adopted_by`); a name here claims nothing, and is the
DECLARATION a reader may refuse -- `forge` is the one to look at first (see `_provenance_rows.py`).

READ AS SOURCE by `dev_lab.dev._provenance.provenance_rows`, never imported, so every value is a
literal. A name in both files is refused there: one module has one provenance.
"""

from __future__ import annotations

from typing import Final

__all__ = ['ORIGINAL_MODULES']

ORIGINAL_MODULES: Final[tuple[str, ...]] = (
    'ab_bench',
    'producer',
    'envseat',
    'verifybox',
    'agent_guard',
    # ORIGINAL rather than a supersession: the three repos' allow blocks were hand-written and
    # nothing generated them, so there is no consumer file this replaced -- only nine rows it now
    # derives or admits. The row consumer-a added by hand on 2026-09-18 is the first thing it subsumes.
    'allow_adoption',
    'inflight',
    'runcache',
    'forgeserve',
    'forgeproduce',
    'forgecarry',
    'footprint',
    'lockreach',
    'localpart',
    'workstationverdict',
    'verdictstore',
    'workstationrevoke',
    'lockpins',
    'lockwait',
    'test_outcomes',
    'serialpass',
    'lanepolicy',
    'platformparts',
    'cjk',
    'content',
    # ORIGINAL, and both halves are the reason. No consumer file is being replaced -- the mechanism
    # is new to the family -- and the two rows that LOOK like candidates are not: `netverb` is the
    # retry wrapper these transports CALL, and `installdoor` asks whether an install delivers a
    # declared build, where this asks whether the resolved build is the CURRENT one. Two subjects, no
    # shared file, so there is no fork to name.
    'dep_observe',
    'depversions',
    'devdocs',
    'docwidth',
    'famconfig',
    # See the module docstring above: declared original against a measured 2-name overlap.
    'forge',
    # No consumer had issue/PR verbs or a token installer to fork: each box ran ``gh``/``tea`` or a
    # browser. Checked 2026-10-01 against every consumer's tracked files.
    'forgeauth',
    'forgecli',
    'forgecred',
    'forgework',
    'forgestatus',
    'forgeoutbox',
    'forgelabels',
    'forgepublish',
    'forgeintent',
    'forgenotice',
    'forgetry',
    'forgewait',
    'branchnotices',
    'lockcheck',
    'relock',
    'forgerecords',
    'forgetick',
    'forgeautosync',
    'forgeintegration',
    'forgemerge',
    'forgereview',
    'forgereview_findings',
    # ORIGINAL: the review read the whole diff or nothing; the slice budget and lenses are new here.
    'forgereview_command',
    'forgereview_scope',
    'forgereview_runtimes',
    'integrate',
    'forgepulls',
    'forgesync',
    'trialmerge',
    'labsession',
    'pradmit',
    'forgerun',
    'forgerunpost',
    'forgerunstate',
    'components',
    'componentbump',
    'shatree',
    'forgeclaim',
    'forgeschedule',
    'forgequeue',
    'forgehosts',
    'forgepoller',
    'forgesettled',
    'forgeprovides',
    'forgetidy',
    'branchprune',
    'branchdelete',
    'forgereview_claim',
    'partrows',
    'forgeoom',
    'forgeslurm',
    'forgeship',
    'artefacts',
    'artefactstores',
    'selection',
    'forgealarm',
    'forgefleet',
    # ORIGINAL: split out of forgetick/forgeserve inside the kit; no consumer held them.
    'forgetake',
    'forgerounds',
    'forgecoalesce',
    'forgeservesteps',
    'forgeunit',
    'forgeorigin',
    'breakglass',
    'forgerequest',
    'retention',
    'retentionplan',
    'diskusage',
    # ORIGINAL in the kit: it absorbs consumer-local push-admission bodies, which live in other trees.
    'pushgate',
    # ORIGINAL: shared demand derived from the forge's run records; no consumer read them (D4).
    'forgedemand',
    'forgeissue',
    'forgeroute',
    # ORIGINAL: both are forge mechanisms of 2026-10-22 with no consumer file before them.
    'forgescarce',
    'prlanded',
    'issueref',
    # ORIGINAL: the merge queue is derived from origin refs and gate statuses; no consumer held one.
    'integrator',
    # ORIGINAL: a consumer's primary-checkout hook guarded the other direction only.
    'sessionbranch',
    # ORIGINAL: no consumer audited a merge's tests; the resolution rule was prose (NEWER-STRUCTURE).
    'mergeaudit',
    # ORIGINAL: how a conflict was resolved was never recorded; the rule was prose (NEWER-STRUCTURE).
    'mergeresolution',
    # ORIGINAL: the principles lived only as ai-lab reviewer data and one private CLAUDE.md; no repo rendered them.
    'principles',
    'principlespage',
    # `scripts/hooks/with-retry.sh` is a REMEDY that resolves in one checkout on earth, which is why
    # `hooks` holds the statements and `hook_adoption` holds the pointer. Neither replaced it.
    'hooks',
    # ORIGINAL rather than superseding `installdoor`, and the distinction is the whole row: it
    # asks whether one COMMAND delivers the declared build, this asks whether a repo's DOOR SET was
    # ever looked at and is still what was measured. Nothing anywhere in the family answered the
    # second -- three consumers adopted `installdoor` with three differently-shaped door sets and no
    # tree could see the other two. There is no path to name because there was no prior mechanism.
    'doorcensus',
    # ORIGINAL, and the row is worth its comment because the thing it measures is THIS package. No
    # prior mechanism asked whether the LEAF carries a consumer's data: the README's tier-1 rule and
    # `.claude/rules/statement-and-mechanism.md` both stated it, both were read on every turn, and
    # the `dev` layer absorbed 38 executable values, 153 unresolvable paths and 181 prose mentions
    # anyway. There is no path to name because prose was the only prior mechanism, and it lost.
    'foreign',
    'installdoor',
    'logref',
    # ORIGINAL: the declared-set census is new; the consumers' origin pins live in famtests.visibility.
    'branchset',
    'family',
    # ORIGINAL: one parse of git's pre-push refspec lines for every pre-push row.
    'refspec',
    # ORIGINAL: the lock PIN moved from a pre-push row into the repo's own forge-judged suite (2026-10-24).
    'lockpin',
    # ORIGINAL: lock freshness and branch set as forge statuses on a PR head (2026-10-24).
    'forgeheadgate',
    # ORIGINAL: the door table and its two renderings are new (AUTO-MODE-RUNS-THE-DOORS).
    'autodoors',
    # ORIGINAL: the injected-text budget and its consumer body are new (INJECTED-TEXT-IS-PROGRESSIVE).
    'disclosure',
    'injectedtext',
    # ORIGINAL in code: generalises a consumer's --pid process-tree killer, kept there until adoption.
    'stoprun',
    # ORIGINAL: the Stop hook sending a handed-over command back to the agent (2026-10-26).
    'handback',
    'servelanes',
    'servelock',
    'servetask',
    'workstation',
    'workstationfile',
    'workstationprobe',
    'workstationregistry',
    # ORIGINAL: user ruling 2026-10-30, a resource a repo produces no part for.
    'unproduced',
    'hostrefresh',
    # ORIGINAL: the clean-only removal door is new; it encodes a consumer's incident, not its code.
    'worktrees',
    # ORIGINAL: no consumer ever removed a finished worktree; the lease decision is new here.
    'reclaim',
    'reclaimrun',
    # ORIGINAL: the scan was lab-commons' own test helper, which is in-kit and so not provenance; no
    # consumer held a copy, which is why each published one had no guard at all.
    'privatemarkers',
    'profile',
    'quantity_values',
    'reports',
    'reportplace',
    'rules',
    'supersede',
    # ORIGINAL rather than superseding consumer-a' `scripts/gate/dep_sync.py`, and the distinction is
    # the pair's whole point. That script MUTATES an environment and reports what it removed
    # AFTERWARDS; these two never touch one and answer BEFOREHAND, from command text joined to a
    # manifest. Nothing in the family answered "which extras survive" -- `_doorcensus_rows` names it
    # as an ABSENT mechanism rather than implying coverage -- so there is no prior code to name.
    # The TEST-TREE half of the same question, and the one `syncscope`'s docstring names as
    # unmeasurable from a manifest. No prior code in any repo read a test tree for its imports:
    # `testfacts` reads marks and timeouts from the same AST and never an import.
    'collectscope',
    'synccensus',
    'syncscope',
    'unit_slices',
    'units',
    'verdict',
    'remedypaths',
    # ORIGINAL, for `dep_observe`'s reason read the other way round: this is the VERDICT half whose
    # readings are `depversions`'s, so the consumer file it would supersede is the one this lane
    # EXISTS to write next -- a per-repo copy of `test_dependencies_take_the_latest.py` that reads a
    # different question today (a ceiling in the declaration, not a frozen resolution).
    'latestversions',
    # THE OTHER HALF OF THAT PAIR, and the boundary was settled by measurement rather than by taste.
    # NOT inside `untimedwaits`, which is the SCAN: that one imports `ast`, takes a `Path`, returns a
    # pinnable SET, refuses BEFORE anything runs and needs a floor. This imports `subprocess`/`time`/
    # `os`, SPAWNS A REAL PROCESS TREE, asserts on ELAPSED TIME, refuses ONE LIVE WAIT and needs no
    # floor -- it has a calibration instead. Measured 2026-09-18: the overlap between the two
    # surfaces is EMPTY. NOT on `dev.bounded` either: 293 lines plus this body lands past the 400
    # band, and `famtests` is where a body a CONSUMER'S architecture test is judged by lives.
    # `untimedwaits`' own docstring already pointed at `bounded.wall_reason` for the sized-ceiling
    # claim; the pointer existed and the module it should have pointed at did not. The readings half,
    # `famtests/_boundedremedy_readings.py`, is private and has no row.
    'boxneeds',
    # ORIGINAL: no consumer file asserted onboarding as one statement; the five repos each failed on a
    # different missing piece (2026-10-20), so there was no local copy for this body to supersede.
    'onboarding',
    # ORIGINAL: no consumer file refused a platform skip; the need arose when an OS became a resource a host
    # supplies by itself (2026-10-21) and a skipped Windows path was found to run on no host at all.
    'platformskips',
    # ORIGINAL: no consumer file refused a host Node; the need arose when the cluster verdict host was ruled
    # Node-free (2026-10-28) and a downstream repo's review JS tests were found to call shutil.which('node').
    'hostnode',
    # ORIGINAL, and it is the only kind it could honestly be: no consumer file asserts this, because
    # nobody had a word for the shape until `boundedremedy`'s own `wider_tier in text` clause was
    # driven on an absent tier word and passed in all three repos on 2026-09-18.
    # NOT inside `untimedwaits`, whose walk shape it shares: that one reads CALLS and asks whether a
    # wait declares a ceiling; this reads DATA FLOW inside one body and asks whether an assertion can
    # fail at all. Measured the same day, the two surfaces share `take_scan` and nothing else, and
    # one is entirely about `subprocess` while the other never mentions it. NOT inside `citedtests`
    # either, the nearest neighbour BY SUBJECT -- a declaration that lies -- which reads PROSE
    # against the whole tree where this cannot see across a single function boundary.
    'echoedtoken',
    # ORIGINAL in the kit: refuses consumer-local push-admission copies once `admission` exists.
    'localadmission',
    # ORIGINAL, and it is the only kind it could honestly be: no consumer file asks this question, and
    # the absence is the finding rather than a gap in the search. All four placement rosters STORE the
    # density reading that decided each row in that row's `why` prose, all four re-derive that reading
    # elsewhere, and not one compares the two -- so a number goes stale silently and the roster, which
    # is the family's migration progress meter, over-states the work left. Measured 2026-09-19 with
    # this module pointed at them: 210 stored readings across 96 rows disagree with re-deriving them,
    # in four repos that were all green. NOT `placement`, which reads the manifest's KEYS against a
    # walk and bounds two bars against readings PASSED to it -- it never opens a row's prose. NOT
    # `rostercensus` either, which reads a row's SIDE against the published kit and is blind to the
    # numbers under it. NOT `density`, which is the METER: it computes a reading and judges nothing,
    # and this judges a SENTENCE against whatever meter the consumer supplies.
    'storedreadings',
    'venvspelling',
    # ORIGINAL: no consumer holds a guard it would supersede; it refuses their re-declared settings.
    'sharedsettings',
    # ORIGINAL for the reason `venvspelling` states one row up: what it centralises is a STRING,
    # not a forked file.
    'venvpath',
    # ORIGINAL: no consumer file ran JS on a declared engine; every JS test called `shutil.which('node')` until the
    # Node-free cluster verdict host (2026-10-28) made that host dependency red.
    'jsrun',
    'worktreeplace',
    'ephemeralrefs',
    'famfiles',
    # ORIGINAL: an audit (2026-10-21) found consumer pages restating registry rules, and no consumer
    # file refused the copy -- there is nothing to supersede.
    'restatedrules',
    # ORIGINAL: SPLIT-BY-CONCEPT was prose until this body; no consumer guard read module names.
    'sizesplits',
    # -- `dev_lab.dev.githooks`: the TOML hook table and its runner, and the per-file checks.
    'table',
    'runner',
    'filechecks',
    'ciworkflows',
    # No consumer guard is superseded: these forge-launching verbs moved from the lab-commons
    # owner into dev-lab in 9ac2e681. "original" denotes no consumer fork, not newly written code.
    'account',
    'allocate',
    'checks',
    'deploy',
    'fleet',
    'spec',
    'steps',
    'tick',
    # ORIGINAL: new mechanisms no consumer held a file for.
    'automode',
    'forgestuck',
    'forgewatch',
    'jobparts',
    'pushwatch',
    'liverun',
    'metrics',
    'monthsummary',
    'prsuperseded',
    'worktree_archive',
    # ORIGINAL: the forge's review/security gate, new here; and the in-kit splits of `metrics` and
    # `forge` (a split of a kit module supersedes no CONSUMER file, so it inherits the parent's kind).
    'forgecontexts',
    'forgereview_dispose',
    'forgereview_rounds',
    'forgesecurity',
    'forgetakeover',
    'metrics_compute',
    'metrics_report',
    'reviewcommand',
    'reviewbudget',  # the review's round and dollar caps, new here
    'commandpart',  # a non-pytest repo's one command part, new here
    'forgeaffinity',  # HPC account affinity of verify parts, new here
    'forgereview_judge',  # independent re-judging and claim adjudication, new here
    'forgerunshow',  # a cluster run's findings published on the forge, new here
    'memoryadds',  # memory is added to, never edited, new here
    'remconfig',  # the family's rem.json, new here
    'reviewgate',  # the one reviewed-head predicate, new here
    'reviewgitauth',  # the review door's file-held tokens, new here
    'reviewpolicy',  # the review policy exported for every trigger, new here
    'forgedraft',  # a PR opens as a draft until its author marks it ready (D53), new here
    'hostalarm',  # a pressed host tells its agents and its humans (D54), new here
    'security',
)
