"""REACH-EQUIVALENCE: a part's verdict at A carries to a descendant B whose diff touches only inert paths.

Every diff here is a REAL ``git diff`` in a temp repo; the forge is a per-sha store of status posts.
The planted control in each pair is the code-touching descendant: same history shape, one non-inert path.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _forge_fake import git_out, run_git

from lab_commons.config import CONFIG_ENV
from lab_commons.dev import forgecarry, forgeproduce, forgerun
from lab_commons.dev.forgeclaim import Claim, Work
from lab_commons.dev.forgestatus import Status
from lab_commons.dev.platformparts import Part, parts_of, standing
from lab_commons.dev.shatree import Tree

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
REF = 'integrate/main'
INERT = '[tool.lab_commons.parts]\noutput = "output/logs"\ninert = [".claude/memory/**", "docs-src/**", "*.md"]\n'


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    run_git(root, 'add', '-A')
    run_git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git_out(root, 'rev-parse', 'HEAD')


def _repo(root: Path, pyproject: str = INERT) -> str:
    """A repo whose first commit declares *pyproject*; that commit, the judged sha A."""
    run_git(root, 'init', '-q')
    return _commit(root, {'pyproject.toml': pyproject, 'src/a.py': 'x = 1\n'}, 'a')


def _push(root: Path, sha: str) -> None:
    run_git(root, 'update-ref', f'refs/remotes/origin/{REF}', sha)


DOCS = {'.claude/memory/2026/10/13/plan.md': 'status: done\n', 'docs-src/x.txt': 'y\n', 'README.md': 'r\n'}


def test_a_docs_only_descendant_is_equivalent_and_any_code_path_is_not(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    docs = _commit(tmp_path, DOCS, 'docs')
    assert forgecarry.changed_paths(tmp_path, a, docs) == tuple(sorted(DOCS))
    assert forgecarry.equivalent(tmp_path, a, docs)
    code = _commit(tmp_path, {'src/a.py': 'x = 2\n', 'notes.md': 'n\n'}, 'code')
    assert not forgecarry.equivalent(tmp_path, a, code), 'one non-inert path in the diff refuses the carry'
    assert not forgecarry.equivalent(tmp_path, docs, code)


def test_a_rename_out_of_an_inert_tree_counts_both_paths(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    _commit(tmp_path, {'docs-src/tool.py': 'z = 1\n'}, 'docs')
    run_git(tmp_path, 'mv', 'docs-src/tool.py', 'src/tool.py')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mv')
    moved = git_out(tmp_path, 'rev-parse', 'HEAD')
    assert 'src/tool.py' in (forgecarry.changed_paths(tmp_path, a, moved) or ())
    assert not forgecarry.equivalent(tmp_path, a, moved)


def test_nothing_declared_or_a_non_descendant_never_carries(tmp_path: Path) -> None:
    a = _repo(tmp_path, '[tool.lab_commons.parts]\noutput = "output/logs"\n')
    docs = _commit(tmp_path, DOCS, 'docs')
    assert not forgecarry.equivalent(tmp_path, a, docs), 'no inert list: every path can reach a test'
    run_git(tmp_path, 'checkout', '-q', '-b', 'side', a)
    sibling = _commit(tmp_path, {'README.md': 's\n'}, 'side')
    assert forgecarry.changed_paths(tmp_path, docs, sibling) is None, 'not a descendant: there is no diff to judge'
    assert not forgecarry.equivalent(tmp_path, docs, sibling)


def test_an_inert_list_that_is_not_strings_is_refused_by_name(tmp_path: Path) -> None:
    a = _repo(tmp_path, '[tool.lab_commons.parts]\ninert = "*.md"\n')
    with pytest.raises(ValueError, match=r'\[tool\.lab_commons\.parts\] inert'):
        forgecarry.inert_globs(tmp_path, a)


def test_a_carried_part_names_its_source_and_still_admits() -> None:
    part = Part('windows', 'full', 'PASS', 12, carried='a' * 12)
    text = part.description()
    assert text.endswith(f'carried from {"a" * 12}: only inert paths changed')
    parts, problems = parts_of([Status('tests/windows', 'success', text, '')])
    assert problems == ()
    assert parts['windows'] == part
    assert standing([Status('tests/windows', 'success', text, '')], head='b' * 40, scope='full').result == 'PASS'


class _Forge:
    """Every status post, PER SHA, ids ascending -- what a carry reads on A and writes on B."""

    def __init__(self) -> None:
        self.posts: dict[str, list[Status]] = {}

    def post(self, _client, sha, *, context, state, description, target_url='') -> Status:
        made = Status(context, state, description, target_url, id=len(self.posts.get(sha, ())) + 1)
        self.posts.setdefault(sha, []).append(made)
        return made

    def history(self, _client, sha) -> tuple[Status, ...]:
        return tuple(self.posts.get(sha, ()))


class _Proc:
    """A producer that, during its *beats* heartbeats, sees origin move to *then*, and posts its verdict on exit."""

    def __init__(self, forge: _Forge, sha: str, root: Path, then: str, beats: int = 2) -> None:
        self.forge, self.sha, self.root, self.then, self.beats = forge, sha, root, then, beats
        self.pid, self.stdout, self.killed = None, iter(()), False

    def wait(self, timeout: float | None = None) -> int:
        if self.beats and not self.killed:
            self.beats -= 1
            _push(self.root, self.then)
            cmd = 'fake'
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        if not self.killed:
            verdict = 'scope=full ran=7 hands=- nowhere=0'
            self.forge.post(None, self.sha, context='tests/windows', state='success', description=verdict,
                            target_url='https://f/record')  # fmt: skip
        return 0

    def kill(self) -> None:
        self.killed = True


def _produce(monkeypatch: pytest.MonkeyPatch, root: Path, a: str, then: str) -> tuple[_Forge, _Proc]:
    forge = _Forge()
    monkeypatch.setattr(forgeproduce, 'status_post', forge.post)
    monkeypatch.setattr(forgeproduce, 'status_history', forge.history)
    monkeypatch.setattr(forgecarry, 'status_history', forge.history)
    monkeypatch.setattr(forgeproduce, 'open_tree', lambda _r, sha: Tree(root / sha[:12], root / 'python'))
    monkeypatch.setattr(forgeproduce, 'close_tree', lambda _r, sha, **_k: f'tree {sha[:12]}: removed')
    _push(root, a)
    proc = _Proc(forge, a, root, then)
    client = SimpleNamespace(answered=format_datetime(NOW, usegmt=True), whoami=lambda: 'alice')
    forgeproduce.produce(
        root, Work(REF, a, 'windows', 'mine', ME, argv=('verify',)), client=lambda _r: client,
        spawn=lambda *_a, **_k: proc, clock=lambda: NOW, say=lambda _l: None, lease=timedelta(hours=6),
        renew_s=1, fetch=lambda _r: None,
    )  # fmt: skip
    return forge, proc


def test_a_docs_only_descendant_keeps_the_local_run_and_gets_the_carried_status(monkeypatch, tmp_path: Path) -> None:
    a = _repo(tmp_path)
    b = _commit(tmp_path, DOCS, 'docs')
    forge, proc = _produce(monkeypatch, tmp_path, a, b)
    assert not proc.killed, 'a reach-equivalent tip lets the run finish'
    (carried,) = forge.history(None, b)
    assert (carried.context, carried.state, carried.url) == ('tests/windows', 'success', 'https://f/record')
    expected = f'scope=full ran=7 hands=- nowhere=0 carried from {a[:12]}: only inert paths changed'
    assert carried.description == expected


def test_a_code_touching_descendant_still_supersedes(monkeypatch, tmp_path: Path) -> None:
    a = _repo(tmp_path)
    b = _commit(tmp_path, {'src/a.py': 'x = 2\n'}, 'code')
    forge, proc = _produce(monkeypatch, tmp_path, a, b)
    assert proc.killed
    assert forge.history(None, a)[-1].description == f'superseded by {b[:12]}'
    assert forge.history(None, b) == ()


def test_a_tip_already_settled_is_never_overwritten_by_a_carry(monkeypatch, tmp_path: Path) -> None:
    a = _repo(tmp_path)
    b = _commit(tmp_path, DOCS, 'docs')
    forge = _Forge()
    forge.post(None, b, context='tests/windows', state='failure', description='scope=full ran=7 hands=- nowhere=0')
    monkeypatch.setattr(forgecarry, 'status_history', forge.history)
    _push(tmp_path, b)
    assert forgecarry.carry_target(tmp_path, None, ref=REF, sha=a, platform='windows') == ''
    assert forgecarry.carry_target(tmp_path, None, ref=REF, sha=a, platform='linux') == b


class _Slurm:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def cancel(self, run: forgerun.Run) -> list[str]:
        self.cancelled += run.job_ids
        return list(run.job_ids)


def test_a_cluster_run_survives_a_docs_only_tip_and_a_code_tip_cancels_it(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    root = tmp_path / 'repo'
    root.mkdir()
    a = _repo(root)
    b = _commit(root, DOCS, 'docs')
    forge = _Forge()
    monkeypatch.setattr(forgerun, 'status_post', forge.post)
    run = forgerun.Run('https://f/o/r.git', a, REF, 'tests', str(tmp_path), ME.description(),
                       phase=forgerun.SUBMITTED, job_ids=('77',))  # fmt: skip
    forgerun.save(run)
    _push(root, b)
    slurm = _Slurm()
    kept = forgerun.supersede_moved(root, [run], client=None, cluster=slurm, say=lambda _l: None)
    assert (kept, slurm.cancelled) == ([run], [])
    c = _commit(root, {'src/a.py': 'x = 3\n'}, 'code')
    _push(root, c)
    assert forgerun.supersede_moved(root, [run], client=None, cluster=slurm, say=lambda _l: None) == []
    assert slurm.cancelled == ['77']
    assert forge.history(None, a)[-1].description == f'superseded by {c[:12]}'


def test_a_published_cluster_part_is_also_posted_on_the_equivalent_tip(monkeypatch, tmp_path: Path) -> None:
    """The run's record is posted on A, then the same record onto B as a carried part; no tip, no second post."""
    monkeypatch.setenv(CONFIG_ENV, str(tmp_path / 'home' / 'config.toml'))
    monkeypatch.setattr(forgerun, 'route', lambda *_a: ())
    monkeypatch.setattr(forgerun, 'pyproject_at', lambda _root, _sha: '')
    monkeypatch.setattr(forgerun, 'read_record', lambda _path: {})
    monkeypatch.setattr(forgerun, '_hold', lambda run, **_k: ('advance', run))
    posted: list[tuple[str, str]] = []
    monkeypatch.setattr(forgecarry, 'post', lambda _root, path, onto='': posted.append((path.name, onto)) or '')
    for target, expected in (('b' * 40, [('r.json', ''), ('r.json', 'b' * 40)]), ('', [('r.json', '')])):
        posted.clear()
        monkeypatch.setattr(forgecarry, 'carry_target', lambda *_a, _t=target, **_k: _t)
        run = forgerun.Run('https://f/o/r.git', 'a' * 40, REF, 'tests', str(tmp_path), ME.description(),
                           phase=forgerun.GATHERED, record=str(tmp_path / 'r.json'))  # fmt: skip
        forgerun.save(run)
        forgerun.advance(tmp_path, run, client=None, me=ME, lease=timedelta(hours=6), cluster=None,
                         say=lambda _l: None, alarm=lambda _a: None)  # fmt: skip
        assert posted == expected
