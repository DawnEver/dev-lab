"""THE LIVE HALF: the kit's pruning commands re-measured against its own working tree.

`test_dev_syncscope.py` proves the reader can fail, over planted manifests. THIS file is a
MEASUREMENT -- which commands in this repo's declared doors move a population -- so a new `uv sync`
cannot join quietly. The kit makes no extras selection of its own (`_synccensus_rows`); each consumer
declares its own and calls `assert_scopes` over its own checkout. Nothing here installs, syncs or prunes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from dev_lab.dev._doorcensus_rows import DOORS
from dev_lab.dev._synccensus_rows import SITE_COMMAND_FLOOR, SITES
from dev_lab.dev.doorcensus import door_text, reachable
from dev_lab.dev.installdoor import commands
from dev_lab.dev.synccensus import pruning_sites

#: This repo's checkout, and the directory it sits in -- the census API joins the two.
_ROOT: Final = Path(__file__).resolve().parents[1]
_BASE: Final = _ROOT.parent

#: The repo under verification, read from its WORKING TREE.
_HERE: Final = 'dev-lab'

_PATHS: Final[dict[str, str]] = {_HERE: _ROOT.name}


def _door_texts() -> dict[tuple[str, str], str]:
    """Every declared door file of this repo, keyed by ``(repo, path)``."""
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


def test_this_repo_has_no_pruning_command_no_row_accounts_for() -> None:
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


def test_a_pruning_command_planted_into_a_real_door_is_found() -> None:
    """THE SCAN'S OWN CONTROL: a `uv sync` planted into a copy of this repo's real Makefile, through the real scanner.

    The live scan reads no pruning site, and an empty reading proves nothing alone: the same text with
    one population-moving command added must surface exactly that command. Nothing is installed.
    """
    text = (_ROOT / 'Makefile').read_text(encoding='utf-8')
    assert pruning_sites({('dev-lab', 'planted'): text}) == ()
    planted = text + '\nsync:\n\tuv sync --frozen\n'
    assert pruning_sites({('dev-lab', 'planted'): planted}) == (('dev-lab', 'planted', 'uv sync --frozen'),)
