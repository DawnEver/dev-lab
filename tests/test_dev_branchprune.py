"""MERGED-BRANCHES-PRUNED, driven on a REAL bare origin through a fake forge that deletes in it.

The forge's half -- the open pull requests, the live tip, the deletion -- is answered by :class:`BareForge`,
which reads and deletes refs in a real bare repository, so "deleted through the forge API" is checked against
what ``git ls-remote`` then sees, and the ancestry and idle reads run on real refs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev.branchprune import DELETABLE, DELETE, EPHEMERAL, MERGED, STALE, prune, serve_prune, survey
from dev_lab.dev.branchset import BranchSet, BranchSetNotDeclared, declared_branchset
from dev_lab.dev.forgealarm import PRUNED, STALE_BRANCH, Alarm
from dev_lab.dev.forgefailure import ForgeCallFailed
from dev_lab.dev.forgework import Client
from dev_lab.dev.lanepolicy import Policy, load_policy
from dev_lab.dev.netverb import Attempt, Diagnosis, Report
from tests._forge_state import API, FORGE

_GIT = shutil.which('git') or 'git'
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
OLD = '2026-10-10T12:00:00+00:00'
YOUNG = '2026-10-13T11:00:00+00:00'
POLICY = Policy(integration='integrate/main', trunk='main')

_MANIFEST = """[project]
name = "planted"
version = "0"

[tool.dev_lab.branchset]
trunk = "main"
sessions = ["integrate/main", "feat/session"]
{extra}
[tool.dev_lab.integrator]
integration = "integrate/main"
"""


def _git(cwd: Path, *args: str, date: str = OLD) -> str:
    env = {**os.environ, 'GIT_COMMITTER_DATE': date, 'GIT_AUTHOR_DATE': date}
    done = subprocess.run(
        [_GIT, '-c', 'user.email=t@t', '-c', 'user.name=t', *args],
        cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )  # fmt: skip
    return done.stdout.strip()


def _commit(root: Path, name: str, *, date: str = OLD) -> None:
    (root / name).write_text(name, encoding='utf-8')
    _git(root, 'add', name, date=date)
    _git(root, 'commit', '-qm', name, date=date)


def _planted(tmp_path: Path, *, extra: str = '') -> tuple[Path, Path]:
    """A checkout and its bare origin carrying every shape the prune must tell apart."""
    origin, root = tmp_path / 'origin.git', tmp_path / 'root'
    _git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(origin))
    _git(tmp_path, 'init', '-q', '-b', 'main', str(root))
    (root / 'pyproject.toml').write_text(_MANIFEST.format(extra=extra), encoding='utf-8')
    _git(root, 'add', 'pyproject.toml')
    _git(root, 'commit', '-qm', 'c0')
    _git(root, 'remote', 'add', 'origin', str(origin))
    for name, date in (('lane/merged', OLD), ('lane/young', YOUNG), ('lane/with-pr', OLD), ('feat/session', OLD)):
        _git(root, 'checkout', '-qb', name, 'main')
        _commit(root, name.replace('/', '-'), date=date)
    _git(root, 'checkout', '-qb', 'lane/unmerged', 'main')
    _commit(root, 'unmerged')
    _git(root, 'checkout', '-qb', 'integrate/main', 'main')
    for name in ('lane/merged', 'lane/young', 'lane/with-pr', 'feat/session'):
        _git(root, 'merge', '-q', '--no-ff', '-m', f'merge {name}', name)
    _git(root, 'push', '-q', 'origin', '--all')
    _git(root, 'fetch', '-q', '--prune', 'origin')
    return root, origin


class BareForge(Client):
    """A forge whose branches ARE the bare repository's refs; *moved* answers another tip for those names."""

    def __init__(self, origin: Path, *, pulls: tuple[str, ...] = ('lane/with-pr',)) -> None:
        """A forge over the bare repository *origin*, with one open pull request per name in *pulls*."""
        super().__init__(FORGE, 'T', sleep=lambda _s: None)
        self.origin = origin
        self.pulls = pulls
        self.moved: set[str] = set()
        self.deleted: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def _tip(self, name: str) -> dict[str, Any]:
        found = subprocess.run(
            [_GIT, 'rev-parse', '--verify', '--quiet', f'refs/heads/{name}'],
            cwd=self.origin, capture_output=True, text=True, encoding='utf-8', check=False, timeout=60,
        )  # fmt: skip
        if found.returncode:
            missing = Attempt(1, 404, 'branch does not exist', Diagnosis.FORGE_REFUSED)
            raise ForgeCallFailed(Report(('GET', name), (missing,), 1))
        sha = 'f' * 40 if name in self.moved else found.stdout.strip()
        return {'name': name, 'commit': {'id': sha}}

    def call(self, method: str, path: str, body: object = None, landed: object = None) -> object:
        del body, landed
        route, _, _ = path.partition('?')
        self.calls.append((method, route))
        if route == '/api/v1/user':
            return {'login': 'a'}
        if route == f'{API}/pulls':
            return [
                {
                    'number': n, 'title': head, 'state': 'open', 'body': '', 'html_url': f'u/{n}',
                    'user': {'login': 'a'}, 'head': {'ref': head}, 'base': {'ref': 'integrate/main'},
                }
                for n, head in enumerate(self.pulls, start=1)
            ]  # fmt: skip
        name = urllib.parse.unquote(route.removeprefix(f'{API}/branches/'))
        if method == 'GET':
            return self._tip(name)
        assert method == 'DELETE', (method, path)
        subprocess.run([_GIT, 'update-ref', '-d', f'refs/heads/{name}'], cwd=self.origin, check=True, timeout=60)
        self.deleted.append(name)
        return None


def _on_origin(origin: Path) -> set[str]:
    out = _git(origin, 'for-each-ref', '--format=%(refname:short)', 'refs/heads/')
    return set(out.splitlines())


def _prune(root: Path, forge: BareForge) -> tuple[list[str], list[Alarm], tuple]:
    said: list[str] = []
    alarms: list[Alarm] = []
    rows = prune(root, forge, now=NOW, say=said.append, alarm=alarms.append)
    return said, alarms, rows


# ---------------------------------------------------------------------------------------------- the declaration


def test_the_declaration_defaults_to_listing_only(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path)
    declared = declared_branchset(root)
    assert declared.prune_merged is False
    assert declared.grace_hours == pytest.approx(24.0, abs=0.0)  # exact: the default as declared


def test_the_declaration_opts_in_and_names_its_grace(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path, extra='prune_merged = true\ngrace_hours = 48\n')
    declared = declared_branchset(root)
    assert (declared.prune_merged, declared.grace_hours) == (True, 48.0)


@pytest.mark.parametrize('extra', ['prune_merged = "yes"\n', 'grace_hours = -1\n', 'prune = true\n'])
def test_a_malformed_or_unknown_key_is_refused_by_name(tmp_path: Path, extra: str) -> None:
    root, _ = _planted(tmp_path, extra=extra)
    with pytest.raises(BranchSetNotDeclared, match=extra.split(maxsplit=1)[0]):
        declared_branchset(root)


# ---------------------------------------------------------------------------------------------- the survey


def test_the_survey_names_merged_idle_and_unmerged_stale_and_nothing_else(tmp_path: Path) -> None:
    """Declared, young, and open-PR branches are never rows; the acquittal half is asserted by NAME."""
    root, _ = _planted(tmp_path)
    rows = survey(root, declared_branchset(root), load_policy(root), open_heads=frozenset({'lane/with-pr'}), now=NOW)
    assert {(r.ref, r.rule, r.action) for r in rows} == {
        ('lane/merged', MERGED, DELETABLE),
        ('lane/unmerged', 'unmerged-stale', STALE),
    }
    (stale,) = [r for r in rows if r.action == STALE]
    assert stale.idle_h == pytest.approx(72.0, abs=1e-9)  # hours; whole-second commit dates


def test_opting_in_turns_deletable_into_delete(tmp_path: Path) -> None:
    root, _ = _planted(tmp_path)
    branchset = BranchSet('main', frozenset({'integrate/main', 'feat/session'}), prune_merged=True)
    rows = survey(root, branchset, load_policy(root), open_heads=frozenset(), now=NOW)
    assert {r.ref for r in rows if r.action == DELETE} == {'lane/merged', 'lane/with-pr'}


# ---------------------------------------------------------------------------------------------- the prune


def test_prune_deletes_only_the_merged_idle_branch_logs_it_and_alarms(tmp_path: Path) -> None:
    root, origin = _planted(tmp_path, extra='prune_merged = true\n')
    forge = BareForge(origin)
    said, alarms, _ = _prune(root, forge)
    assert forge.deleted == ['lane/merged']
    assert _on_origin(origin) == {
        'main',
        'integrate/main',
        'feat/session',
        'lane/young',
        'lane/with-pr',
        'lane/unmerged',
    }
    (event,) = [json.loads(line) for line in said if line.startswith('{')]
    sha = _git(root, 'rev-parse', 'refs/remotes/origin/lane/merged')
    assert event == {'event': 'lab_commons.forge.prune', 'ref': 'lane/merged', 'sha': sha, 'rule': MERGED}
    by_kind = {a.kind: a for a in alarms}
    assert set(by_kind) == {PRUNED, STALE_BRANCH}
    assert 'lane/merged' in by_kind[PRUNED].body
    assert sha[:12] in by_kind[PRUNED].body
    assert 'lane/unmerged' in by_kind[STALE_BRANCH].body
    assert '72 h' in by_kind[STALE_BRANCH].body


def test_the_stale_alarm_names_ahead_behind_and_the_two_next_commands(tmp_path: Path) -> None:
    """Each stale row says how far it is from integration and what to run: open its PR, or abandon it."""
    root, origin = _planted(tmp_path)
    _, alarms, _ = _prune(root, BareForge(origin))
    (stale,) = [a for a in alarms if a.kind == STALE_BRANCH]
    behind = _git(root, 'rev-list', '--count', 'refs/remotes/origin/lane/unmerged..refs/remotes/origin/integrate/main')
    assert f'1 ahead, {behind} behind integrate/main' in stale.body, stale.body
    pr = 'python -m dev_lab.dev.forge pr create --head lane/unmerged --base integrate/main --title'
    assert pr in stale.body, stale.body
    assert 'git push origin --delete lane/unmerged' in stale.body, stale.body
    assert 'lane/merged' not in stale.body, 'control: a merged branch is never offered for abandonment'


def test_prune_off_deletes_nothing_and_still_alarms_the_stale_one(tmp_path: Path) -> None:
    root, origin = _planted(tmp_path)
    forge = BareForge(origin)
    _, alarms, rows = _prune(root, forge)
    assert forge.deleted == []
    assert not [c for c in forge.calls if c[0] == 'DELETE']
    assert {r.ref for r in rows if r.action == DELETABLE} == {'lane/merged'}
    assert [a.kind for a in alarms] == [STALE_BRANCH]


def test_a_branch_that_moved_since_the_survey_is_kept(tmp_path: Path) -> None:
    """The deletion is pinned to the judged sha: a tip that moved is somebody's new work."""
    root, origin = _planted(tmp_path, extra='prune_merged = true\n')
    forge = BareForge(origin)
    forge.moved.add('lane/merged')
    said, alarms, _ = _prune(root, forge)
    assert forge.deleted == []
    assert 'lane/merged' in _on_origin(origin)
    assert any('moved' in line and 'lane/merged' in line for line in said), said
    assert PRUNED not in {a.kind for a in alarms}


class RacedForge(BareForge):
    """Another host deletes each branch between this host's read of its tip and this host's DELETE."""

    def call(self, method: str, path: str, body: object = None, landed: object = None) -> object:
        if method != 'DELETE':
            return super().call(method, path, body, landed)
        name = urllib.parse.unquote(path.partition('?')[0].removeprefix(f'{API}/branches/'))
        subprocess.run([_GIT, 'update-ref', '-d', f'refs/heads/{name}'], cwd=self.origin, check=True, timeout=60)
        gone = Attempt(1, 404, 'branch does not exist', Diagnosis.FORGE_REFUSED)
        raise ForgeCallFailed(Report(('DELETE', name), (gone,), 1))


def test_any_host_prunes_and_a_racing_second_delete_is_a_no_op(tmp_path: Path) -> None:
    """No owner: every host prunes. PLANTED: the loser of a race neither raises nor alarms a failure."""
    root, origin = _planted(tmp_path, extra='prune_merged = true\n')
    alarms: list[Alarm] = []
    said: list[str] = []
    serve_prune(root, RacedForge(origin), now=NOW, say=said.append, alarm=alarms.append)
    assert 'lane/merged' not in _on_origin(origin)
    assert PRUNED not in {a.kind for a in alarms}, 'a delete another host already made is no failure'
    assert any('another host deleted it first' in line for line in said), said
    forge = BareForge(origin)
    _git(origin, 'update-ref', 'refs/heads/lane/merged', _git(root, 'rev-parse', 'origin/lane/merged'))
    serve_prune(root, forge, now=NOW, say=lambda _l: None, alarm=alarms.append)
    assert forge.deleted == ['lane/merged'], 'the uncontested host deletes'


# ------------------------------------------------------------------------------------- ephemeral namespaces


def test_an_ephemeral_branch_is_deleted_once_no_open_pr_heads_it_merged_or_not(tmp_path: Path) -> None:
    """A ``pr/*`` head is the forge's to delete once its PR is gone -- even unmerged, even without the opt-in.

    PLANTED controls: the same namespace with an OPEN PR on it is kept, and a young one is kept (grace).
    """
    root, _ = _planted(tmp_path)
    for name, date in (('pr/done', OLD), ('pr/open', OLD), ('pr/young', YOUNG)):
        _git(root, 'checkout', '-qb', name, 'main')
        _commit(root, name.replace('/', '-'), date=date)
        _git(root, 'push', '-q', 'origin', name)
    _git(root, 'fetch', '-q', 'origin')
    branchset = BranchSet('main', frozenset({'integrate/main', 'feat/session'}), ephemeral=('pr/*',))
    rows = survey(root, branchset, POLICY, open_heads=frozenset({'pr/open'}), now=NOW)
    assert {(r.ref, r.rule, r.action) for r in rows if r.ref.startswith('pr/')} == {('pr/done', EPHEMERAL, DELETE)}
