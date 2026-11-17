"""MERGED-HEADS-NEVER-PILE-UP (user ruling D25, 2026-11-17): every PR merge deletes an ephemeral head.

Break-glass passed ``delete_branch=False`` while the integration path passed the branch set's ``is_ephemeral``, so
merged ``pr/*`` heads piled up on origin. The decision now lives inside the ONE merge call
(:func:`dev_lab.dev.forgemergecall.merge`); no caller chooses. PLANTED CONTROL: a second merge call in ``src`` --
the way a path could keep an ephemeral head again -- is convicted by the same scanner the test runs over ``src``.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from _forge_state import StateForge

from dev_lab.dev import forgemergecall
from dev_lab.dev.branchset import FAMILY_EPHEMERAL, BranchSet
from dev_lab.dev.forge import Forge

_BRANCHSET = BranchSet('main', frozenset({'integrate/main', 'session/keep'}), ephemeral=FAMILY_EPHEMERAL)


@pytest.mark.parametrize('host', ['gitea.example', 'github.com'])
@pytest.mark.parametrize(('branch', 'deleted'), [('pr/x', True), ('session/keep', False)])
def test_every_merge_deletes_an_ephemeral_head_and_keeps_a_long_lived_one(
    host: str, branch: str, *, deleted: bool
) -> None:
    forge = StateForge(Forge(host, 'o', 'r'))
    number = forge.add_pull(branch, 'integrate/main', sha='a' * 40)
    forgemergecall.merge(forge, number, head='a' * 40, branch=branch, branchset=_BRANCHSET, message='s\n\nb')
    ((_, body),) = forge.merges
    gone = forge.deleted_refs == [branch] if host == 'github.com' else body['delete_branch_after_merge']
    assert gone is deleted


def _asks_a_merge(text: str) -> bool:
    """Whether *text* asks a forge to merge a PR -- the call only :mod:`~dev_lab.dev.forgemergecall` may make."""
    return bool(re.search(r'pulls/\{[^}]*\}/merge\b|\bdelete_branch', text))


def test_no_merge_path_chooses_whether_the_head_goes() -> None:
    assert 'delete_branch' not in inspect.signature(forgemergecall.merge).parameters
    src = Path(forgemergecall.__file__).parents[1]
    callers = sorted(p.relative_to(src).as_posix() for p in src.rglob('*.py') if _asks_a_merge(p.read_text('utf-8')))
    assert callers == ['dev/forgemergecall.py'], f'merge only through forgemergecall.merge: {callers}'


def test_the_scanner_convicts_a_second_merge_call() -> None:
    """PLANTED CONTROL: what break-glass did, written as a second merge call, is caught."""
    assert _asks_a_merge("client.call('PUT', f'{repo}/pulls/{n}/merge', {'sha': head})")
    assert _asks_a_merge('merge_pr(client, n, delete_branch=False)  # .../merge')
    assert not _asks_a_merge("client.call('GET', f'{repo}/pulls/{n}')  # tests/merge-ready")
