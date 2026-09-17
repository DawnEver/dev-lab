"""The gate's diff base, driven against REAL temporary git repositories.

Nothing here is mocked. Every arm builds a checkout, makes commits, moves branches and then asks the
question, because the property under test is "what does git say about ancestry", and a fake that
answered ancestry questions would be a second implementation agreeing with the first.

THE REBASE ARM IS THE POINT. It reconstructs the measured 2026-09-06 situation -- a stale pushed ref
that is STILL a legitimate ancestor of HEAD, so the admission rule cannot reject it and only the
narrowing rule keeps the base honest. A test suite without that arm passes against the
first-admitted-wins version this replaced.
"""

from __future__ import annotations

import inspect
import shutil
import subprocess
from pathlib import Path

import pytest

from lab_commons.dev.gatebase import ZERO_SHA, admitted, gate_base

_TRUNK = 'trunk'


#: Resolved once, so the fixture drives the same git the module under test resolves.
_GIT = shutil.which('git') or 'git'


def _git(root: Path, *args: str) -> str:
    """One git command in *root*, failing loudly -- a broken fixture must not read as a finding."""
    done = subprocess.run([_GIT, *args], cwd=root, capture_output=True, text=True, check=True, timeout=60)
    return done.stdout.strip()


def _commit(root: Path, message: str) -> str:
    """One commit touching one file, and its sha."""
    (root / 'work.txt').write_text(message, encoding='utf-8')
    _git(root, 'add', 'work.txt')
    _git(root, 'commit', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A checkout with a trunk, an integration line and a lane -- the shape the rule is about."""
    root = tmp_path / 'checkout'
    root.mkdir()
    _git(root, 'init', '-q', '-b', _TRUNK)
    _git(root, 'config', 'user.email', 'fixture@example.invalid')
    _git(root, 'config', 'user.name', 'Fixture')
    _commit(root, 'trunk 1')
    return root


def test_the_only_admitted_candidate_wins(repo: Path) -> None:
    """THE FLOOR: with one real ancestor, the function answers it rather than the fallback."""
    _git(repo, 'branch', 'integration')
    _commit(repo, 'lane 1')
    assert gate_base(repo, ['integration'], fallback=_TRUNK) == 'integration'


def test_the_NARROWEST_admitted_candidate_wins_and_not_the_FIRST(repo: Path) -> None:
    """THE 2026-09-06 MEASUREMENT, reconstructed: a stale ref that is a genuine ancestor of HEAD.

    ``stale`` sits three commits back and IS an ancestor, so the admission rule must accept it.
    ``integration`` sits one commit back. First-admitted-wins answers ``stale`` and hands the gate
    three commits it has already judged; narrowest-wins answers ``integration``.
    """
    _git(repo, 'branch', 'stale')
    _commit(repo, 'upstream 1')
    _commit(repo, 'upstream 2')
    _git(repo, 'branch', 'integration')
    _commit(repo, 'lane 1')
    assert admitted(repo, ['stale', 'integration']) == ('stale', 'integration')
    assert gate_base(repo, ['stale', 'integration'], fallback=_TRUNK) == 'integration'


def test_a_TIE_goes_to_the_earlier_candidate_so_priority_still_decides_something(repo: Path) -> None:
    """``min`` is stable, which is how a hook-supplied ref keeps its standing when nothing is narrower."""
    _git(repo, 'branch', 'from_the_hook')
    _git(repo, 'branch', 'integration')
    _commit(repo, 'lane 1')
    assert gate_base(repo, ['from_the_hook', 'integration'], fallback=_TRUNK) == 'from_the_hook'
    assert gate_base(repo, ['integration', 'from_the_hook'], fallback=_TRUNK) == 'integration'


def test_a_ref_HEAD_DOES_NOT_DESCEND_FROM_is_refused_so_the_gate_cannot_SKIP_commits(repo: Path) -> None:
    """THE DANGEROUS DIRECTION, planted: a force-pushed sibling that HEAD is not built on.

    Admitting it would make the gate skip everything the two branches do not share -- commits no
    remote has seen. The fallback is the correct answer here, and it is the wider one.
    """
    _git(repo, 'checkout', '-q', '-b', 'sibling')
    _commit(repo, 'sibling only')
    _git(repo, 'checkout', '-q', _TRUNK)
    _commit(repo, 'trunk 2')
    assert admitted(repo, ['sibling']) == ()
    assert gate_base(repo, ['sibling'], fallback=_TRUNK) == _TRUNK


@pytest.mark.parametrize('ref', ['', ZERO_SHA, 'no/such/ref', 'origin/never-existed'])
def test_an_unresolvable_or_all_zero_ref_is_never_admitted(repo: Path, ref: str) -> None:
    """The all-zero sha is what a NEW branch pushes as its "from"; it looks like a sha and is not one."""
    _commit(repo, 'trunk 2')
    assert admitted(repo, [ref]) == ()


def test_a_real_ancestor_is_admitted_so_the_refusals_above_are_not_blanket(repo: Path) -> None:
    """THE PLANTED CONTROL IN THE OTHER DIRECTION for every refusal arm."""
    head = _commit(repo, 'trunk 2')
    _commit(repo, 'trunk 3')
    assert admitted(repo, [head]) == (head,)


def test_HEAD_ITSELF_is_admitted_and_gives_a_zero_commit_increment(repo: Path) -> None:
    """The narrowest base there is. It must not be refused by an off-by-one in the ancestry test."""
    head = _git(repo, 'rev-parse', 'HEAD')
    assert gate_base(repo, [head], fallback=_TRUNK) == head


def test_NOTHING_admitted_falls_back_to_what_the_CALLER_named(repo: Path) -> None:
    """The fallback is the repo's widest honest base, and this module does not know what that is."""
    assert gate_base(repo, ['no/such/ref'], fallback='some/other/trunk') == 'some/other/trunk'


def test_an_unreadable_directory_admits_NOTHING_rather_than_answering_a_ref(tmp_path: Path) -> None:
    """A directory that is not a checkout must fall back, never claim an ancestor it could not read."""
    assert admitted(tmp_path, ['main']) == ()
    assert gate_base(tmp_path, ['main'], fallback='trunk') == 'trunk'


@pytest.mark.parametrize(
    ('candidates', 'fallback', 'fragment'),
    [([], 'trunk', 'at least one candidate'), (['trunk'], '', 'fallback ref')],
)
def test_an_empty_candidate_list_or_fallback_is_REFUSED(
    repo: Path, candidates: list[str], fallback: str, fragment: str
) -> None:
    """Both halves of the repo's answer are required, and neither may be supplied by omission."""
    with pytest.raises(ValueError, match=fragment):
        gate_base(repo, candidates, fallback=fallback)


def test_the_FALLBACK_has_no_default() -> None:
    """The no-default rule, read off the signature.

    ``origin/main`` as a default is wrong in any repo whose trunk is named otherwise, and it fails in
    the worst direction available: the base resolves to nothing, the increment is unmeasurable, and
    the lane reports clean.
    """
    fallback = inspect.signature(gate_base).parameters['fallback']
    assert fallback.kind is inspect.Parameter.KEYWORD_ONLY
    assert fallback.default is inspect.Parameter.empty
    assert inspect.signature(gate_base).parameters['candidates'].default is inspect.Parameter.empty
