"""THE FOURTEEN ROWS THREE TRANCHES MEASURED BY HAND on 2026-09-17 -- DATA.

They are the only reason the instrument beside them is worth shipping.

`lab_commons.dev.supersede` exists because a placement roster declared 17 MOVES and 7 were real. The
question that makes it more than a plausible idea is whether it reproduces the SEVENTEEN-TO-SEVEN
correction without being told the answer. These rows are that test set: each one carries what a
tranche concluded BY READING (`hand`) and what the instrument must conclude from the kit's published
source (`expected`), and the two are kept as separate fields precisely so a disagreement has
somewhere to live instead of being tuned away.

WHY THE ROWS ARE FACTS AND NOT PATHS. The consumer is motronics-studio's LANE worktree, which this
repo's suite cannot read and must not depend on. So each row carries the derived facts -- its
declared side, its public surface, the kit modules it imports -- captured from that tree on
2026-09-17. The KIT side is NOT captured: it is read live off `src/lab_commons/dev/`, so deleting a
provenance sentence or renaming a published function reds this, which is the half that can rot.

TWO ROWS WERE RECOVERED FROM GIT, not from disk: `scripts/gate/bounded.py` and `scripts/gate/_box.py`
were deleted by the lane's own commit ff50483 the same day, which is what "already in the kit" means
for them. Their surfaces come from that commit's parent.

THE CONTROL IS IN THE SET, not beside it. `_symbol_coverage.py` publishes `survey`, and so does
`lab_commons.dev.checkout`, which has nothing whatever to do with it: a name-matching census
convicts it against the wrong module. It is here so that the instrument's refusal to treat overlap
as a detector is EXERCISED by the same run that validates the positives.

ONE DECLARED DISAGREEMENT, and it is stated rather than smoothed. `scripts/gate/width.py` reads
PARTIAL where the tranche said STAYS. The tranche is right that the file did not leave; the roster
ITSELF records the residual as `BELOW_THE_BAR` with its numbers, so PARTIAL is naming a split the
roster already admits rather than contradicting it. It is counted as a disagreement anyway, because
a fixture that reclassifies its own misses has stopped measuring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from lab_commons.dev.supersede import CONSULTS, NAMED_ONLY, PARTIAL, SUPERSEDED, UNMEASURABLE, UNTOUCHED

__all__ = [
    'ALREADY_IN_THE_KIT',
    'DISAGREEMENTS',
    'MEASURED_ROWS',
    'ROW_FLOOR',
    'STILL_LOCAL',
    'MeasuredRow',
]

#: The hand verdicts, in the words the tranches used.
ALREADY_IN_THE_KIT: Final = 'already_in_the_kit'
STILL_LOCAL: Final = 'still_local'

#: Below the 13 rows held here. A floor, not a second pin on the count: adding a measured row must
#: not red, and a fixture that lost its rows must.
ROW_FLOOR: Final = 10


@dataclass(frozen=True)
class MeasuredRow:
    """One row as three tranches left it, plus the grade the instrument owes it."""

    path: str
    side: str
    public: frozenset[str]
    imports: frozenset[str]
    hand: str
    expected: str


#: Rows where the instrument's grade and the hand verdict point opposite ways, each with its reason.
#: An empty dict would be the stronger result and claiming one falsely is the weaker fixture.
DISAGREEMENTS: Final[dict[str, str]] = {
    'scripts/gate/width.py': (
        'the tranche said STAYS and the file did not leave; the instrument says PARTIAL because '
        '`bounded` claims it by name and holds 1 of its 7 public names. The roster already carries '
        'this file as a BELOW_THE_BAR residual, so the two readings agree about the FACT and '
        'disagree about the label. Counted as a miss regardless.'
    ),
}

MEASURED_ROWS: Final[tuple[MeasuredRow, ...]] = (
    MeasuredRow(
        path='scripts/gate/_box.py',
        side='moves',
        public=frozenset(['available_gb', 'logical_cores', 'worker_width']),
        imports=frozenset(),
        hand=ALREADY_IN_THE_KIT,
        expected=SUPERSEDED,
    ),
    MeasuredRow(
        path='scripts/gate/bounded.py',
        side='moves',
        public=frozenset(['REAP_AFTER_KILL_S', 'run_bounded', 'terminate_tree']),
        imports=frozenset(),
        hand=ALREADY_IN_THE_KIT,
        expected=SUPERSEDED,
    ),
    MeasuredRow(
        path='scripts/gate/runner.py',
        side='stays',
        public=frozenset(
            [
                'CITABLE_BY_TIER',
                'CITABLE_GATE_VERDICT',
                'CITABLE_HEAVY_VERDICT',
                'Composed',
                'HEAVY_MEASURE_WALL_S',
                'HEAVY_PER_TEST_TIMEOUT_S',
                'LIVE_VENDOR_ENV',
                'MEASUREMENT_STAMP',
                'Measurement',
                'PER_TEST_TIMEOUT_S',
                'PUSH_ID_ENV',
                'RunFacts',
                'TIERS',
                'TRUNCATION_MARKERS',
                'VERDICT_STAMP',
                'VERDICT_TIERS',
                'Verdict',
                'WALL_S',
                'build_parser',
                'census_from_output',
                'compose',
                'coverage_note',
                'dated_log',
                'duration_env',
                'durations_dir',
                'env_key',
                'exit_code_of',
                'facts_from_output',
                'gate_base',
                'gate_module',
                'light_paths',
                'load_by_path',
                'lock_what',
                'parse_verdict_line',
                'promote',
                'pytest_argv',
                'record_citable',
                'run_tier',
                'shard_anchor',
                'shard_paths',
                'shard_population',
                'tier_env',
                'touched_heavy_tests',
                'tree_env',
                'tree_sha',
                'tree_stamp',
                'tree_stamp_of',
                'tree_state',
                'verdict_dirt',
            ]
        ),
        imports=frozenset(['bounded', 'bypath', 'envkey']),
        hand=STILL_LOCAL,
        expected=NAMED_ONLY,
    ),
    MeasuredRow(
        path='scripts/gate/wall_reason.py',
        side='stays',
        public=frozenset(),
        imports=frozenset(['bypath']),
        hand=STILL_LOCAL,
        expected=UNMEASURABLE,
    ),
    MeasuredRow(
        path='scripts/gate/width.py',
        side='stays',
        public=frozenset(
            [
                'BLAS_THREAD_VARS',
                'HEADROOM_GB',
                'PROVEN_WIDTH',
                'blas_threads',
                'reset_frozen_width',
                'worker_count',
                'xdist_width',
            ]
        ),
        imports=frozenset(),
        hand=STILL_LOCAL,
        expected=PARTIAL,
    ),
    MeasuredRow(
        path='scripts/lanes/prune_lanes.py',
        side='splits',
        public=frozenset(),
        imports=frozenset(),
        hand=STILL_LOCAL,
        expected=UNTOUCHED,
    ),
    MeasuredRow(
        path='scripts/lanes/prune_origin_branches.py',
        side='moves',
        public=frozenset(['PROTECTED', 'delete_on_origin', 'line']),
        imports=frozenset(['checkout']),
        hand=ALREADY_IN_THE_KIT,
        expected=PARTIAL,
    ),
    MeasuredRow(
        path='scripts/lanes/session_branches.py',
        side='moves',
        public=frozenset(['classify']),
        imports=frozenset(['checkout']),
        hand=ALREADY_IN_THE_KIT,
        expected=SUPERSEDED,
    ),
    MeasuredRow(
        path='scripts/repo/_notices.py',
        side='stays',
        public=frozenset(
            [
                'FAMILIES',
                'HEADINGS',
                'UNKNOWN',
                'family',
                'git_sources',
                'grouped',
                'normalize_license',
                'python_packages',
                'rust_crates',
                'table',
            ]
        ),
        imports=frozenset(),
        hand=STILL_LOCAL,
        expected=UNTOUCHED,
    ),
    MeasuredRow(
        path='scripts/repo/_symbol_coverage.py',
        side='moves',
        public=frozenset(['Coverage', 'definitions', 'mentions', 'parse', 'survey', 'symbols_under']),
        imports=frozenset(),
        hand=ALREADY_IN_THE_KIT,
        expected=PARTIAL,
    ),
    MeasuredRow(
        path='scripts/repo/docs.py',
        side='splits',
        public=frozenset(
            [
                'NOTICES_ABSENT_MEANS',
                'RUST_CRATES_EXCLUDED',
                'SHARED_DOCS_ROOT',
                'SITE_TITLE',
                'SUBSITES',
                'build_all',
                'primary_checkout',
            ]
        ),
        imports=frozenset(['docsite']),
        hand=STILL_LOCAL,
        expected=CONSULTS,
    ),
    MeasuredRow(
        path='scripts/repo/forge_protect.py',
        side='moves',
        public=frozenset(['Forge', 'PUSH_WHITELIST', 'describe', 'forge_from_origin', 'token_for']),
        imports=frozenset(),
        hand=STILL_LOCAL,
        expected=UNTOUCHED,
    ),
    MeasuredRow(
        path='scripts/repo/legal_notices.py',
        side='stays',
        public=frozenset(
            [
                'NOTICE_BASENAME',
                'UnknownLicense',
                'build_notices',
                'notices_markdown',
                'refuse_unknown',
                'render',
            ]
        ),
        imports=frozenset(),
        hand=STILL_LOCAL,
        expected=UNTOUCHED,
    ),
    MeasuredRow(
        path='scripts/repo/worktree_debris.py',
        side='moves',
        public=frozenset(
            [
                'PROTECTED',
                'WORKTREES',
                'orphan_directories',
                'registered_worktrees',
                'render',
                'report',
                'stale_branches',
            ]
        ),
        imports=frozenset(),
        hand=ALREADY_IN_THE_KIT,
        expected=PARTIAL,
    ),
)
