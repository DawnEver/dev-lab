"""REACH-EQUIVALENCE: a part's verdict at A carries to a descendant B whose diff reaches no test's footprint.

Every diff here is a REAL ``git diff`` in a temp repo; the forge is a per-sha store of status posts.
The planted control in each pair is the code-touching descendant: same history shape, one path a test imports.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from _box_fake import ended, record
from _forge_fake import git_out, run_git
from lab_commons.config import CONFIG_ENV
from lab_commons.outcomes import Conclusion

from dev_lab.dev import forgecarry, forgeproduce, forgerun, forgerunstate
from dev_lab.dev.forgeclaim import Claim, Work
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.platformparts import Part, parts_of, standing
from dev_lab.dev.shatree import Tree

NOW = datetime(2026, 10, 13, 12, tzinfo=UTC)
ME = Claim('G', 'alice', NOW + timedelta(hours=6))
REF = 'integrate/main'
PYPROJECT = '[tool.lab_commons.parts]\noutput = "output/logs"\n'
TEST = 'from a import x\nimport b\n\n\ndef test_x():\n    assert x == 1\n'


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    run_git(root, 'add', '-A')
    run_git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return git_out(root, 'rev-parse', 'HEAD')


def _repo(root: Path) -> str:
    """A repo whose one test imports ``src/a.py`` (and a ``b`` it does not hold); its first commit, the sha A."""
    run_git(root, 'init', '-q')
    return _commit(root, {'pyproject.toml': PYPROJECT, 'src/a.py': 'x = 1\n', 'tests/test_a.py': TEST}, 'a')


def _push(root: Path, sha: str) -> None:
    run_git(root, 'update-ref', f'refs/remotes/origin/{REF}', sha)


DOCS = {'.claude/memory/2026/10/13/plan.md': 'status: done\n', 'docs-src/x.txt': 'y\n', 'README.md': 'r\n'}


def test_a_docs_only_descendant_is_equivalent_and_any_reached_path_is_not(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    docs = _commit(tmp_path, DOCS, 'docs')
    assert forgecarry.changed_paths(tmp_path, a, docs) == tuple(sorted(DOCS))
    assert forgecarry.equivalent(tmp_path, a, docs)
    code = _commit(tmp_path, {'src/a.py': 'x = 2\n', 'notes.md': 'n\n'}, 'code')
    assert not forgecarry.equivalent(tmp_path, a, code), 'one path a test imports refuses the carry'
    assert not forgecarry.equivalent(tmp_path, docs, code)


def test_a_rename_out_of_an_unreached_tree_counts_both_paths(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    _commit(tmp_path, {'docs-src/b.py': 'z = 1\n'}, 'docs')
    run_git(tmp_path, 'mv', 'docs-src/b.py', 'src/b.py')
    run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'mv')
    moved = git_out(tmp_path, 'rev-parse', 'HEAD')
    assert 'src/b.py' in (forgecarry.changed_paths(tmp_path, a, moved) or ())
    assert not forgecarry.equivalent(tmp_path, a, moved), 'src/b.py is a candidate of `import b`'


def test_a_non_descendant_never_carries(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    docs = _commit(tmp_path, DOCS, 'docs')
    run_git(tmp_path, 'checkout', '-q', '-b', 'side', a)
    sibling = _commit(tmp_path, {'README.md': 's\n'}, 'side')
    assert forgecarry.changed_paths(tmp_path, docs, sibling) is None, 'not a descendant: there is no diff to judge'
    assert not forgecarry.equivalent(tmp_path, docs, sibling)


def test_a_carried_part_names_its_source_and_still_admits() -> None:
    part = Part('base', 'full', Conclusion.PASS, 12, carried='a' * 12)
    text = part.description()
    assert text.endswith(f'carried from {"a" * 12}: docs-only')
    parts, problems = parts_of([CommitStatus('tests/base', 'success', text, '')])
    assert problems == ()
    assert parts['base'] == part
    assert (
        standing([CommitStatus('tests/base', 'success', text, '')], head='b' * 40, scope='full').result
        is Conclusion.PASS
    )


class _Forge:
    """Every status post, PER SHA, ids ascending -- what a carry reads on A and writes on B."""

    def __init__(self) -> None:
        self.posts: dict[str, list[CommitStatus]] = {}

    def post(self, _client, sha, *, context, state, description, target_url='') -> CommitStatus:
        made = CommitStatus(context, state, description, target_url, id=len(self.posts.get(sha, ())) + 1)
        self.posts.setdefault(sha, []).append(made)
        return made

    def history(self, _client, sha) -> tuple[CommitStatus, ...]:
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
            verdict = 'scope=full ran=7 hands=-'
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
    monkeypatch.setattr(forgeproduce, 'open_tree', lambda _r, sha, _c: Tree(root / sha[:12], root / 'python'))
    monkeypatch.setattr(forgeproduce, 'close_tree', lambda _r, sha, _c, **_k: f'tree {sha[:12]}: removed')
    _push(root, a)
    proc = _Proc(forge, a, root, then)
    client = SimpleNamespace(answered=format_datetime(NOW, usegmt=True), whoami=lambda: 'alice')
    forgeproduce.produce(
        root, Work(REF, a, 'windows', 'mine', ME, argv=('verify',)), client=lambda _r: client,
        spawn=lambda argv, **_k: record(argv, ended(0)) or proc, clock=lambda: NOW, say=lambda _l: None,
        lease=timedelta(hours=6),
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
    expected = f'scope=full ran=7 hands=- carried from {a[:12]}: docs-only'
    assert carried.description == expected


def test_a_part_under_test_finishes_and_posts_while_a_code_push_queues(monkeypatch, tmp_path: Path) -> None:
    """A PART UNDER TEST IS NOT SUPERSEDED (design item 9): A finishes and posts on A; nothing lands on B."""
    a = _repo(tmp_path)
    b = _commit(tmp_path, {'src/a.py': 'x = 2\n'}, 'code')
    forge, proc = _produce(monkeypatch, tmp_path, a, b)
    assert not proc.killed
    posted = forge.history(None, a)[-1]
    assert (posted.state, posted.url) == ('success', 'https://f/record')
    assert forge.history(None, b) == (), 'B queues for its own run: a code change carries nothing from A'


def test_a_tip_already_settled_is_never_overwritten_by_a_carry(monkeypatch, tmp_path: Path) -> None:
    a = _repo(tmp_path)
    b = _commit(tmp_path, DOCS, 'docs')
    forge = _Forge()
    forge.post(None, b, context='tests/windows', state='failure', description='scope=full ran=7 hands=-')
    monkeypatch.setattr(forgecarry, 'status_history', forge.history)
    _push(tmp_path, b)
    assert forgecarry.carry_target(tmp_path, None, ref=REF, sha=a, platform='windows') == ''
    assert forgecarry.carry_target(tmp_path, None, ref=REF, sha=a, platform='base') == b


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
        run = forgerunstate.Run('https://f/o/r.git', 'a' * 40, REF, 'tests', str(tmp_path), ME.description(),
                           phase=forgerunstate.GATHERED, record=str(tmp_path / 'r.json'))  # fmt: skip
        forgerunstate.save(run)
        forgerun.advance(tmp_path, run, client=None, me=ME, lease=timedelta(hours=6), cluster=None,
                         say=lambda _l: None, alarm=lambda _a: None)  # fmt: skip
        assert posted == expected


def test_read_by_is_the_runs_own_then_its_nearest_ancestors(tmp_path: Path) -> None:
    """The ONE selection the cluster carry reads and retention keeps: c4's own run first, then c3 c2 c1."""
    run_git(tmp_path, 'init', '-q')
    shas = []
    for i in range(5):
        run_git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--allow-empty', '-m', f'c{i}')
        shas.append(git_out(tmp_path, 'rev-parse', 'HEAD'))
    assert forgecarry.read_by(tmp_path, shas[4], shas) == [shas[4], shas[3], shas[2], shas[1]]
    assert forgecarry.read_by(tmp_path, shas[4], shas[:4]) == [shas[3], shas[2], shas[1]], 'PLANTED CONTROL: no own run'


_VERDICT = CommitStatus('tests/base', 'success', 'scope=full ran=7 hands=-', 'https://f/record', 1)


def _stand(**by_sha: object) -> Callable[[str], object]:
    return lambda sha: by_sha.get(sha, '')


def test_a_docs_only_head_carries_the_previous_tested_heads_verdict_and_a_code_head_does_not(tmp_path: Path) -> None:
    """DOCS-ONLY-CARRIES (user ruling 2026-10-21): memory written after the code commit costs no new test run.

    PLANTED CONTROL: the same history shape with one path a test imports -- the head runs itself.
    """
    a = _repo(tmp_path)
    docs = _commit(tmp_path, DOCS, 'docs')
    carry = forgecarry.docs_only(tmp_path, docs, _stand(**{a: _VERDICT}))
    assert carry is not None
    assert (carry.source, carry.verdict) == (a, _VERDICT)
    assert carry.hold == f'carried from {a[:12]}: docs-only'
    code = _commit(tmp_path, {'src/a.py': 'x = 2\n'}, 'code')
    assert forgecarry.docs_only(tmp_path, code, _stand(**{a: _VERDICT})) is None


def test_a_docs_only_head_on_a_running_head_waits_for_its_result(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    docs = _commit(tmp_path, DOCS, 'docs')
    carry = forgecarry.docs_only(tmp_path, docs, _stand(**{a: forgecarry.RUNNING}))
    assert carry is not None
    assert (carry.source, carry.verdict) == (a, None)
    assert carry.hold.startswith(f'waiting behind {a[:12]}')
    assert forgecarry.docs_only(tmp_path, docs, _stand()) is None, 'PLANTED CONTROL: nothing tested before: it runs'


def test_a_data_only_head_a_whole_tree_scan_reaches_waits_for_the_running_head_instead_of_running_beside_it(
    tmp_path: Path,
) -> None:
    """The cause of docs(memory) heads running full suites (motronics a3b326d0a829, 2026-10-20).

    A test that reads the whole tree (``reads = ["*"]``) reaches a memory diff, so the head is not equivalent
    -- and it ran BESIDE its running parent, so nothing could be carried and every outcome ran again. Now a head
    whose diff holds no Python, no ``ALWAYS`` path and no ``everywhere`` glob waits for the running head; once
    that settles the head runs, carrying every outcome its diff cannot reach (:func:`forgecarry.carry_from`).

    PLANTED CONTROLS: the same head on a SETTLED parent runs (no verdict is carried); a code head never waits.
    """
    run_git(tmp_path, 'init', '-q')
    scan = 'from pathlib import Path\n\n\ndef test_scan():\n    assert Path(__file__).parent.exists()\n'
    a = _commit(
        tmp_path,
        {
            'pyproject.toml': PYPROJECT + '[tool.lab_commons.carry.reads]\n"tests/test_scan.py" = ["*"]\n',
            'src/a.py': 'x = 1\n',
            'tests/test_a.py': TEST,
            'tests/test_scan.py': scan,
        },
        'a',
    )
    docs = _commit(tmp_path, DOCS, 'docs')
    assert not forgecarry.equivalent(tmp_path, a, docs), 'the whole-tree scan reaches the memory diff'
    waits = forgecarry.docs_only(tmp_path, docs, _stand(**{a: forgecarry.RUNNING}))
    assert waits is not None
    assert (waits.source, waits.verdict) == (a, None)
    assert waits.hold.startswith(f'waiting behind {a[:12]} (data-only')
    assert forgecarry.docs_only(tmp_path, docs, _stand(**{a: _VERDICT})) is None, 'settled: it runs, carrying'
    code = _commit(tmp_path, {'src/a.py': 'x = 2\n'}, 'code')
    assert forgecarry.docs_only(tmp_path, code, _stand(**{docs: forgecarry.RUNNING})) is None


def test_a_docs_only_head_reads_through_untested_docs_heads_but_never_past_untested_code(tmp_path: Path) -> None:
    a = _repo(tmp_path)
    _commit(tmp_path, {'notes.md': 'n\n'}, 'docs 1')
    docs = _commit(tmp_path, DOCS, 'docs 2')
    through = forgecarry.docs_only(tmp_path, docs, _stand(**{a: _VERDICT}))
    assert through is not None
    assert through.source == a
    run_git(tmp_path, 'checkout', '-q', '-b', 'other', a)
    _commit(tmp_path, {'src/a.py': 'x = 3\n'}, 'untested code')
    stacked = _commit(tmp_path, DOCS, 'docs on code')
    assert forgecarry.docs_only(tmp_path, stacked, _stand(**{a: _VERDICT})) is None, 'the code change needs its run'


def test_a_carried_verdict_names_its_first_origin_and_reads_back_as_a_part() -> None:
    once = forgecarry.DocsOnly('a' * 40, _VERDICT).description('base')
    assert once == f'scope=full ran=7 hands=- carried from {"a" * 12}: docs-only'
    again = CommitStatus('tests/base', 'success', once, '', 2)
    assert forgecarry.DocsOnly('b' * 40, again).description('base') == once, 'an outcome carried again keeps its origin'
    parts, problems = parts_of([again])
    assert (problems, parts['base'].carried) == ((), 'a' * 12)


def test_a_part_carried_under_the_retired_spelling_still_reads_back() -> None:
    old = f'scope=full ran=7 hands=- carried from {"a" * 12}: every outcome carried by footprint'
    parts, problems = parts_of([CommitStatus('tests/base', 'success', old, '')])
    assert (problems, parts['base'].carried) == ((), 'a' * 12)
    assert parts['base'].description().endswith(': docs-only'), 'written back at the current spelling'
