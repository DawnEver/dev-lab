"""THE FOREIGN-DATA REGISTRY, pure DATA -- who the siblings are, and every row evicted by design.

The machinery is :mod:`lab_commons.dev.foreign` and the seam is the one
`test_arch_registry_data_is_separate.py` names for `_rule_rows.py`: a table edited through the
module that checks it drifts away from what it describes, because the same edit that adds a row can
relax the check that would have refused it and the diff looks like one change. Nothing here
computes.

WHY THIS REGISTRY EXISTS AT ALL. This package is the family's LEAF -- the README's tier-1 rule says
it "contains no concept from any single project's domain", and `.claude/rules/statement-and-
mechanism.md` says a row "never grades another repo". Both were being read on every turn while the
`dev` layer absorbed 38 executable data values naming a sibling, 153 unresolvable tree paths -- 60
of them in the rules registry alone -- and 181 prose mentions, across 119 modules. Prose could not
hold the line, so the finding ships as a scan with a two-sided ratchet, and this file is the half a
human edits.

EVERY ENTRY BELOW IS A ROW EVICTED BY DESIGN. It is not an exemption: it is the eviction ORDER, with
the reason the deletion could not happen in the same pass. The consumers cannot be edited from here,
and a row a consumer still reads may not be deleted to make a scan green. When the consumer half
lands, the deletion is mechanical -- remove the row, remove its handle here, and the arm agrees,
because :func:`lab_commons.dev.foreign.assert_no_foreign_data` reds on a handle whose finding is
GONE exactly as it reds on a finding with no handle.

THE MEASUREMENT AND THE PLAN are in `.claude/memory/2026/09/19/the-leaf-ships-its-consumers-data-
and-60-of-78-mechanisms-are-one-repos-paths.md`, which names per module what stays and what moves.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    'EVICTED',
    'PROSE_CEILING',
    'SCAN_FLOOR',
    'SELF',
    'SIBLINGS',
    'SYNTHETIC',
]

#: The repos this one is the leaf of. LONGEST SPELLING FIRST, because ``motronics`` is a prefix of
#: ``motronics-studio`` and a scan that matched the short one first would report the wrong name in
#: its finding -- and a refusal that misnames its subject sends the reader to the wrong tree.
#: A NAMED SET rather than a pattern: a fifth lab joins by being typed here, which is a decision.
SIBLINGS: Final[tuple[str, ...]] = ('motronics-studio', 'wdg-lab', 'optimi-lab', 'motronics')

#: The one module that may name a sibling in executable data, and the exclusion is itself a claim
#: so it is stated rather than left to a reader: this file IS the registry of the violation, and it
#: cannot record who the siblings are without spelling them. Excluding it by NAME rather than by a
#: pattern is what stops the exclusion widening during a red suite.
SELF: Final[tuple[str, ...]] = ('src/lab_commons/dev/_foreign_rows.py',)

#: The scan is vacuous below this. MEASURED 2026-09-19: 117 tracked modules under
#: ``src/lab_commons/``. The floor sits well under it on purpose -- a floor refuses an UNREAD tree,
#: it is not a second pin on the count, and a floor pinned to the measurement reds on every file
#: added, which is how a floor gets deleted.
SCAN_FLOOR: Final = 80

#: The PROSE half is a CEILING and may only fall. MEASURED 2026-09-19: **181** by the scan that
#: enforces it, against **183** read the same day by a line-based grep -- both numbers on record,
#: because the scan is the one that can refuse and a reader who finds the other number deserves to
#: know which instrument took it. The difference is two lines carrying two mentions each.
#:
#: PROSE IS NOT EVICTED ROW BY ROW, because a docstring naming the repo a finding came from is
#: EVIDENCE rather than a mechanism, and rewriting all of them to name the SHAPE instead is the LAST
#: step of this migration rather than the first. The ceiling is what stops the number growing while
#: the other two kinds are being emptied.
PROSE_CEILING: Final = 181

#: ``'<repo-relative module>::<kind>' -> why the deletion is not in this pass``. One handle per
#: module per kind, so a new module or a new kind cannot arrive under an existing waiver.
#:
#: EVERY ONE OF THEM NEEDS A CONSUMER EDIT FIRST, and the first draft of this table claimed two did
#: not -- `agent_guard.py::path` and `rostercensus.py::path`, on the reasoning that a hardcode in
#: MACHINERY is this repo's to fix alone. MEASURED: wdg-lab and optimi-lab both import
#: `famtests.rostercensus` and both name `agent_guard` in their placement rosters, so turning either
#: hardcode into a no-default argument reds two trees. The claim was the exact defect this registry
#: exists to refuse, one layer up, and it is left on record rather than quietly corrected.
EVICTED: Final[dict[str, str]] = {
    'src/lab_commons/dev/_doorcensus_rows.py::data': (
        '20 `DoorRow(repo=...)` values for the three consumers, over 15 rows. Read only by this repo`s own tests -- '
        'wdg-lab`s single mention of `DOORS` is in a COMMENT, measured -- so the deletion reds only '
        'this repo`s floors, and those must be RE-MEASURED by executing the scan rather than '
        'lowered. Blocked on each consumer holding its own census.'
    ),
    'src/lab_commons/dev/_doorcensus_rows.py::path': (
        '7 consumer `scripts/` paths, one of them `scripts/wdg-lab-update.sh`, which hardcodes a '
        'repo NAME into a path. They travel with the rows above and are deleted with them.'
    ),
    'src/lab_commons/dev/_synccensus_rows.py::data': (
        '3 `ScopeRow(repo=...)` rows, and the sharper miss inside them: `selected=(`pareto`, `dev`)` '
        'is a motronics EXTRA as a live value rather than as prose -- a domain noun the README`s own '
        'test forbids. Same blocker as the door census.'
    ),
    'src/lab_commons/dev/_synccensus_rows.py::path': (
        '2 `scripts/gate/dep_sync.py` literals belonging to the rows above.'
    ),
    'src/lab_commons/dev/_provenance_rows.py::path': (
        '27 motronics `scripts/` paths -- the largest single block. Provenance is a record of where '
        'a module CAME FROM, which is the one reading under which naming another tree is honest; '
        'the migration is to carry the origin REPO beside the path instead of implying it.'
    ),
    'src/lab_commons/dev/_rule_rows.py::path': (
        'THE HEADLINE. 60 of the 78 mechanism paths this registry ships resolve in a consumer and '
        'not here; 58 are motronics-studio alone and 2 name a motronics-only layer outright. They '
        'may NOT simply be deleted: `Rule` refuses a row with no mechanism, so deleting the paths '
        'deletes the rules. The next step is a mechanism that NAMES its proving repo, which changes '
        'the shape `RULES` exposes -- and both wdg-lab and optimi-lab build `Adoption` against it, '
        'so their adoption tests move WITH it in one push train. No `_compat` alias.'
    ),
    'src/lab_commons/dev/_famconfig_ruff_rows.py::data': (
        '3 repo-keyed rows in the ruff base. The base/delta renderer is right; the per-repo delta '
        'belongs in the repo whose delta it is.'
    ),
    'src/lab_commons/dev/famtests/_placement_readings.py::data': (
        '12 readings keyed by roster name. THE WEAKEST OF THE EVICTIONS and deliberately last: '
        'these are EVIDENCE for a published finding, not a bar, and `placement.py` already has the '
        'right shape -- its arms take the two measured readings as arguments with no default, so '
        'nothing can fall back to another repo`s number. What moves is the evidence, once each '
        'roster holds its own.'
    ),
    'src/lab_commons/dev/famtests/_placement_readings.py::path': (
        '4 roster paths (`tests/architecture/_placement.py` and motronics` two layering helpers) '
        'that travel with the readings above.'
    ),
    'src/lab_commons/dev/agent_guard.py::path': (
        'THE THREE `.claude/` PATHS, AND THEY ARE IN THE MACHINERY. `deny-commands.js`, '
        '`deny-rules.json` and `settings.json` resolve in all three consumers and in NEITHER this '
        'checkout -- the guard hardcodes a layout it cannot itself exhibit. The three names become '
        'an argument, which both consumers` placement rosters name `agent_guard` against, so the '
        'edit is theirs to take too.'
    ),
    'src/lab_commons/dev/famtests/rostercensus.py::path': (
        '3 `scripts/repo/worktree_debris.py` literals hardcoded in the MACHINERY, which is worse '
        'than the same path in a data module: a census body that knows one consumer`s filename '
        'cannot be run by a consumer that spells it differently. They sit inside a PLANTED CONTROL, '
        'which is why they are here and not in SYNTHETIC: the plant is shaped like a real file in a '
        'real consumer, and that is what makes it a control rather than a fiction.'
    ),
}

#: PATH-SHAPED CONSTANTS THAT NAME NO TREE AT ALL -- a fixture in a refusal message, a worked
#: example in a docstring`s prose. They do not resolve here, and they are not supposed to: nothing
#: owns `tests/a/test_fast.py`. They are a SEPARATE named set from :data:`EVICTED` because merging
#: them would make the eviction list a lie -- a reader would find rows in it that are never going
#: anywhere, and a waiver list nobody believes is a waiver list nobody reads. Two-sided all the
#: same: if the example goes, the handle goes with it.
SYNTHETIC: Final[dict[str, str]] = {
    'src/lab_commons/dev/durations.py::path': (
        '6 illustrative paths in refusal text -- `tests/integration/test_planted_wedge.py` and the '
        '`tests/a/*` trio -- naming the SHAPE of a slow test, not a file in anybody`s repo.'
    ),
    'src/lab_commons/dev/famtests/venvspelling.py::path': (
        '3 worked examples: `planted/recipe.py`, `planted/narrative.py` and a `lab_commons/dev/`'
        'spelling quoted as text rather than resolved.'
    ),
    'src/lab_commons/dev/famtests/datedmemory.py::path': (
        '1 example lane note, `lanes/a-lane.md`, in the prose that explains the dated shape.'
    ),
}
