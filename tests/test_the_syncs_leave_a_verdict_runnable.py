"""THE LIVE HALF: every recorded sync selection re-measured against the checkouts beside this one.

`test_dev_syncscope.py` proves the reader can fail, over planted manifests. THIS file is a
MEASUREMENT of the family -- which selections exist, and what each of them would leave behind -- so
a recorded scope cannot age quietly into prose. On the day it was written one of them was already a
finding: motronics' `dep_sync` advises `--extra all`, and that selection removes its whole runner.

Nothing here installs, syncs or prunes. A sibling not on this box is ABSENT rather than failing,
because repos are cloned per box; the repo floor is what stops that being a free pass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from lab_commons.dev._doorcensus_rows import DOORS
from lab_commons.dev._synccensus_rows import REPO_FLOOR, ROW_FLOOR, ROWS, SITE_COMMAND_FLOOR, SITES
from lab_commons.dev.doorcensus import door_text, reachable
from lab_commons.dev.installdoor import commands
from lab_commons.dev.synccensus import (
    EvidenceGoneError,
    ScopeDriftError,
    ScopeRow,
    assert_scopes,
    pruning_sites,
)

#: This file is `<lab-commons>/tests/`, so the family sits one level above the repo root.
_BASE: Final = Path(__file__).resolve().parents[2]

#: The repo under verification, whose WORKING TREE is the authority for its own rows; every sibling
#: is read at `HEAD`, so a lane's half-finished edit over there cannot turn this repo red.
_HERE: Final = 'lab-commons'

#: Where each repo is checked out relative to `_BASE`. The motronics entry names a WORKTREE: the
#: main checkout is the integrator's and is never read here.
_PATHS: Final[dict[str, str]] = {
    'lab-commons': 'lab-commons',
    'wdg-lab': 'wdg-lab',
    'optimi-lab': 'optimi-lab',
    'motronics-studio': 'motronics-studio/.claude/worktrees/feat/optimi-lab',
}


def _door_texts() -> dict[tuple[str, str], str]:
    """Every declared door file in the family, keyed by ``(repo, path)``. Missing repos are absent."""
    roots = reachable(_BASE, _PATHS)
    out: dict[tuple[str, str], str] = {}
    for row in DOORS:
        root = roots.get(row.repo)
        if root is None:
            continue
        text = door_text(root, row.path, at_head=row.repo != _HERE)
        if text is not None:
            out[row.repo, row.path] = text
    return out


def test_every_recorded_selection_still_leaves_what_the_table_records() -> None:
    """THE CENSUS. Equality on scope AND on the stranded set, in both directions, per row."""
    seen = assert_scopes(_BASE, _PATHS, ROWS, repo_floor=REPO_FLOOR, row_floor=ROW_FLOOR, here=_HERE)
    assert _HERE in seen, 'the census did not even read the tree it runs in'


def test_the_family_has_no_pruning_command_no_row_accounts_for() -> None:
    """THE OTHER SIDE OF THE RATCHET: a new `uv sync` in a declared door must red, not join quietly.

    EQUALITY, not containment: a declared site that stops pruning is as wrong as an undeclared one
    that starts -- the first is a row protecting nothing, and `DECLARED <= live` is satisfied by
    every shorter declaration, which is exactly how two counts in this family sat green while wrong.
    """
    texts = _door_texts()
    read = sum(len(commands(text)) for text in texts.values())
    assert read >= SITE_COMMAND_FLOOR, (
        f'read {read} installer commands across {len(texts)} declared door files, below the floor of '
        f'{SITE_COMMAND_FLOOR}. Finding no uncensused pruning site in a set that was not read is vacuous.'
    )
    live = pruning_sites(texts)
    declared = tuple(sorted(key for key in SITES if key[0] in {repo for repo, _ in texts}))
    assert live == declared, (
        f'the pruning sites in the family are {list(live)} and the census declares {list(declared)}. '
        f'A command that moves a POPULATION needs a row saying what survives it; a declared site that '
        f'no longer prunes is a row protecting nothing.'
    )


def test_every_declared_site_carries_a_reason_rather_than_a_caption() -> None:
    """A site listed with a caption is a decision nobody made; the floor is what makes the row evidence."""
    assert SITES, 'the site table read empty -- an unread table is not a clean one'
    for key, why in SITES.items():
        assert len(why) >= 150, f'{key} is declared with a {len(why)}-character reason'


def test_the_census_refuses_a_scope_planted_into_the_real_table() -> None:
    """A PLANTED CONTROL ON THE REAL ROWS: the COMPLETE selection recorded as stranding nothing, flipped.

    The plant is the edit that would actually hide the finding -- a row's verdict rewritten to what
    somebody wished it said -- driven through the real guard over the real checkouts.
    """
    broken = tuple(
        ScopeRow(
            row.repo,
            row.path,
            row.line,
            row.evidence,
            row.selected,
            'STRANDS' if row.scope == 'COMPLETE' else 'COMPLETE',
            frozenset({'pytest'}) if row.scope == 'COMPLETE' else frozenset(),
            row.why,
        )
        for row in ROWS
    )
    with pytest.raises(ScopeDriftError, match='records'):
        assert_scopes(_BASE, _PATHS, broken, repo_floor=REPO_FLOOR, row_floor=ROW_FLOOR, here=_HERE)


def test_the_census_refuses_a_row_whose_evidence_line_moved() -> None:
    """The second plant: the same rows pointed one line off, which is what an edit upstream looks like."""
    moved = tuple(
        ScopeRow(row.repo, row.path, row.line + 1, row.evidence, row.selected, row.scope, row.stranded, row.why)
        for row in ROWS
    )
    with pytest.raises(EvidenceGoneError, match='expected'):
        assert_scopes(_BASE, _PATHS, moved, repo_floor=REPO_FLOOR, row_floor=ROW_FLOOR, here=_HERE)


def test_a_pruning_command_planted_into_a_real_door_is_found() -> None:
    """THE SCAN'S OWN CONTROL: the `--no-sync` dropped off this repo's real CI door, through the real scanner.

    The remedy `installdoor` names for a lock-consuming command is the same token that keeps it out
    of THIS census, so removing it must make the file appear as a pruning site. No environment is
    touched; the plant is a string replacement on a copy of the text.
    """
    home = Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'python-verify.yml'
    text = home.read_text(encoding='utf-8')
    assert 'uv run --no-sync make verify' in text, 'the remedy this control plants the removal of is gone'
    planted = {('lab-commons', 'planted'): text.replace('uv run --no-sync', 'uv run')}
    assert ('lab-commons', 'planted', 95) in pruning_sites(planted)
    assert pruning_sites({('lab-commons', 'planted'): text}) == (('lab-commons', 'planted', 83),)
