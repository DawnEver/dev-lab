"""SCARCE-PARTS-BY-REACH: a PR needs a scarce part only where its diff reaches that part's tests (ruling 2026-10-22).

Real git repositories; every rule carries its planted control.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git
from lab_commons.compute.model import BRANCH, PR, Schedule
from lab_commons.hpc.needsets import read_vocabulary, scarce_parts
from lab_commons.outcomes import Conclusion

from dev_lab.dev import forgescarce, forgeschedule
from dev_lab.dev.forgescarce import files_by_part, red_alarms, unreached
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.lanepolicy import Policy
from dev_lab.dev.platformparts import standing

_DECLARED = Policy(integration='integrate/main')  # every repo declares its integration branch (D83)

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
_PYPROJECT = (
    '[tool.lab_commons.tests]\nresources = ["jmag", "windows"]\nscarce = ["jmag"]\n'
    '[tool.dev_lab.parts]\nrefs = { jmag.full = ["integrate/main"] }\n'
)
_RECORD = {'handed': {'tests/test_j.py::test_j': 'jmag'}}


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding='utf-8')
    run_git(repo, 'add', '.')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git_out(repo, 'rev-parse', 'HEAD')


def _repo(tmp_path: Path) -> Path:
    """``integrate/main`` holding a base test of ``pkg.a`` and a jmag test of ``pkg.j``."""
    repo = tmp_path / 'r'
    repo.mkdir()
    run_git(repo, 'init', '-q', '-b', 'integrate/main')
    tip = _commit(
        repo,
        {
            'pyproject.toml': _PYPROJECT,
            'src/pkg/__init__.py': '',
            'src/pkg/a.py': 'A = 1\n',
            'src/pkg/j.py': 'J = 1\n',
            'tests/test_a.py': 'from pkg import a\n\n\ndef test_a():\n    assert a.A\n',
            'tests/test_j.py': 'from pkg import j\n\n\ndef test_j():\n    assert j.J\n',
        },
        'root',
    )
    run_git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', tip)
    return repo


def _pr(repo: Path, path: str) -> str:
    run_git(repo, 'checkout', '-q', '-B', f'pr/{Path(path).stem}', 'refs/remotes/origin/integrate/main')
    return _commit(repo, {path: 'CHANGED = 2\n'}, f'change {path}')


def _status(part: str, state: str, hands: str = '-', sid: int = 1) -> CommitStatus:
    return CommitStatus(f'tests/{part}', state, f'scope=full ran=1 hands={hands}', 'https://f/rec.json.gz', sid)


GREEN_BASE = (_status('base', 'success', 'jmag:1'),)


def test_the_scarce_resources_are_one_declared_subset_of_the_resources() -> None:
    """PLANTED CONTROL: a scarce name the repository does not declare as a resource is refused by name."""
    assert read_vocabulary(_PYPROJECT).scarce == ('jmag',)
    assert scarce_parts(['base', 'jmag', 'jmag+windows', 'windows'], ('jmag',)) == {'jmag', 'jmag+windows'}
    with pytest.raises(ValueError, match='scarce'):
        read_vocabulary('[tool.lab_commons.tests]\nresources = ["femm"]\nscarce = ["jmag"]\n')


def test_a_waived_part_neither_blocks_nor_fails_a_standing() -> None:
    """PLANTED CONTROLS: unwaived, a missing handed-to part is INCONCLUSIVE and its FAIL is a FAIL."""
    assert standing(GREEN_BASE, head='h').result is Conclusion.INCONCLUSIVE
    assert standing(GREEN_BASE, head='h', waived=frozenset({'jmag'})).result is Conclusion.PASS
    red = (*GREEN_BASE, _status('jmag', 'failure', sid=2))
    assert standing(red, head='h').result is Conclusion.FAIL
    assert standing(red, head='h', waived=frozenset({'jmag'})).result is Conclusion.PASS
    claimed = (*GREEN_BASE, CommitStatus('tests/jmag', 'pending', 'claim machine=G', '', 3))
    assert standing(claimed, head='h', waived=frozenset({'jmag'})).result is Conclusion.PASS


def test_a_scarce_part_is_waived_only_where_no_changed_path_reaches_its_tests(tmp_path: Path) -> None:
    """The base record names the jmag part's files; reach is the carry's footprint rule.

    PLANTED CONTROLS: a diff into the jmag test's import closure waives nothing; no record waives nothing.
    """
    repo = _repo(tmp_path)
    forgescarce._REACHED.clear()
    elsewhere = _pr(repo, 'src/pkg/a.py')
    assert unreached(repo, None, 'integrate/main', elsewhere, GREEN_BASE, record=lambda _s: _RECORD) == {'jmag'}
    forgescarce._REACHED.clear()
    inside = _pr(repo, 'src/pkg/j.py')
    assert unreached(repo, None, 'integrate/main', inside, GREEN_BASE, record=lambda _s: _RECORD) == frozenset()
    forgescarce._REACHED.clear()
    assert unreached(repo, None, 'integrate/main', elsewhere, GREEN_BASE, record=lambda _s: None) == frozenset()
    assert files_by_part(_RECORD) == {'jmag': frozenset({'tests/test_j.py'})}


def test_a_pr_is_offered_only_its_reached_scarce_parts_whatever_the_ref_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A waived part is no candidate; a reached one is, past ``refs = { jmag.full = [...] }``.

    PLANTED CONTROL: a lane ``branch`` asking for the same jmag part is still held off by the ref filter.
    """
    repo = _repo(tmp_path)
    head = git_out(repo, 'rev-parse', 'HEAD')
    refs = [('pr/x', head, PR, (), 7, 'bob'), ('lane/y', head, BRANCH, (), 0, '')]
    monkeypatch.setattr(forgeschedule, '_part_refs', lambda *_a, **_k: refs)
    monkeypatch.setattr(forgeschedule, 'head_login', lambda *_a: 'bob')
    monkeypatch.setattr(forgeschedule, '_requests', lambda *_a, **_k: [])

    def offered(waived: frozenset[str]) -> set[tuple[str, str]]:
        found = forgeschedule.candidates(
            repo, None, repo='o/r', parts=lambda _sha: ('base', 'jmag'), schedule=Schedule(), policy=_DECLARED,
            now=NOW, waived=lambda _sha: waived,
        )  # fmt: skip
        return {(one.ref, one.platform) for one in found}

    assert offered(frozenset({'jmag'})) == {('pr/x', 'base'), ('lane/y', 'base')}
    assert offered(frozenset()) == {('pr/x', 'base'), ('pr/x', 'jmag'), ('lane/y', 'base')}


def test_a_red_scarce_part_on_integration_names_the_merges_since_its_last_green_and_their_sessions(
    tmp_path: Path,
) -> None:
    """ONE integration alarm. PLANTED CONTROL: the same tip green raises none."""
    repo = _repo(tmp_path)
    green = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'checkout', '-q', '-b', 'pr/s1')
    _commit(repo, {'src/pkg/j.py': 'J = 0\n'}, 'break j\n\nLab-Session: session_s1')
    run_git(repo, 'checkout', '-q', 'integrate/main')
    run_git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'merge', '-q', '--no-ff', '-m', 'merge s1', 'pr/s1')
    tip = git_out(repo, 'rev-parse', 'HEAD')
    run_git(repo, 'update-ref', 'refs/remotes/origin/integrate/main', tip)
    posted = {green: [_status('jmag', 'success')], tip: [_status('base', 'success'), _status('jmag', 'failure')]}
    (alarm,) = red_alarms(repo, 'integrate/main', 'o/r', lambda sha: tuple(posted.get(sha, ())))
    assert alarm.kind == 'integration'
    assert f'since its last green {green[:12]}' in alarm.body
    assert f'{tip[:12]} merge s1 -- sessions: session_s1' in alarm.body
    posted[tip] = [_status('base', 'success'), _status('jmag', 'success')]
    assert red_alarms(repo, 'integrate/main', 'o/r', lambda sha: tuple(posted.get(sha, ()))) == []
