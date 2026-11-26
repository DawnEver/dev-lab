"""The oracle GC report: every branch of every repo is a root; a partial root set aborts by name."""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import oraclegc
from dev_lab.dev.oraclegc import RootsUnread, render, report

NOW = datetime(2026, 11, 25, tzinfo=UTC)
KEPT, LOOSE, ABSENT, MAIN = ('a' * 64), ('b' * 64), ('c' * 64), ('d' * 64)


def _git(root: Path, *args: str) -> str:
    argv = ['git', '-C', str(root), *args]
    done = subprocess.run(argv, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _commit(root: Path, files: Mapping[str, str]) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'c')
    return _git(root, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A repo whose default branch names MAIN and ABSENT, and whose side branch alone names KEPT."""
    root = tmp_path / 'alpha'
    root.mkdir()
    _git(root, 'init', '-q')
    main = _commit(
        root, {'cases/x/references.lock': f'[[object]]\nsha256 = "{MAIN}"\n[[object]]\nsha256 = "{ABSENT}"\n'}
    )
    side = _commit(root, {'cases/y/references.lock': f'{{"sha256": "{KEPT}"}}\n', 'uv.lock': f'hash = "{LOOSE}"\n'})
    _git(root, 'reset', '-q', '--hard', main)
    return root, {'main': main, 'pr/side': side}


class FakeForge:
    def __init__(self, heads: Mapping[str, Mapping[str, str]], refuse: frozenset[str] = frozenset()) -> None:
        """Heads per repo; *refuse* names repos whose listing fails."""
        self._heads, self._refuse = heads, refuse

    def heads(self, name: str, checkout: Path) -> Mapping[str, str]:
        if name in self._refuse:
            msg = f'{name}: the forge listed no branches (refused)'
            raise RootsUnread(msg)
        return self._heads[name]


class FakeStore:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        """The lsjson rows the store answers."""
        self.rows, self.asked = rows, 0

    def files(self) -> list[dict[str, Any]]:
        self.asked += 1
        return self.rows


def _row(sha: str, size: int, days: int) -> dict[str, Any]:
    return {'Path': f'{sha[:2]}/{sha}', 'Size': size, 'ModTime': (NOW - timedelta(days=days)).isoformat()}


STORE = [_row(KEPT, 10, 3), _row(LOOSE, 2048, 40), _row(MAIN, 7, 1), {'Path': 'stray.txt', 'Size': 1,
         'ModTime': NOW.isoformat()}]  # fmt: skip


def test_an_object_named_only_on_a_non_default_branch_is_kept(repo: tuple[Path, dict[str, str]]) -> None:
    root, heads = repo
    found = report({'alpha': root}, FakeForge({'alpha': heads}), FakeStore(STORE), now=NOW)
    assert KEPT not in {u.stored.sha256 for u in found.unreferenced}
    assert found.referenced == 2  # KEPT and MAIN
    assert found.branches == 2


def test_an_unnamed_object_is_reported_with_size_and_age(repo: tuple[Path, dict[str, str]]) -> None:
    """LOOSE's sha256 sits in a uv.lock, which is not a lock naming objects: it is still unreferenced."""
    root, heads = repo
    found = report({'alpha': root}, FakeForge({'alpha': heads}), FakeStore(STORE), now=NOW)
    assert [(u.stored.sha256, u.stored.bytes, round(u.age_days)) for u in found.unreferenced] == [(LOOSE, 2048, 40)]
    assert found.foreign == ('stray.txt',)
    text = render(found, now=NOW)
    assert LOOSE in text
    assert '- unreferenced: 1 objects' in text


def test_a_lock_naming_a_missing_object_is_reported(repo: tuple[Path, dict[str, str]]) -> None:
    root, heads = repo
    found = report({'alpha': root}, FakeForge({'alpha': heads}), FakeStore(STORE), now=NOW)
    assert [(m.sha256, m.named_by) for m in found.missing] == [
        (ABSENT, ('alpha:main:cases/x/references.lock', 'alpha:pr/side:cases/x/references.lock'))
    ]


def test_an_unreadable_repo_aborts_by_name_before_the_store_is_asked(
    repo: tuple[Path, dict[str, str]], tmp_path: Path
) -> None:
    root, heads = repo
    store = FakeStore(STORE)
    forge = FakeForge({'alpha': heads, 'beta': {}}, refuse=frozenset({'beta'}))
    with pytest.raises(RootsUnread, match='beta'):
        report({'alpha': root, 'beta': tmp_path / 'beta'}, forge, store, now=NOW)
    assert store.asked == 0


def test_a_branch_tip_absent_locally_aborts_naming_the_fetch(repo: tuple[Path, dict[str, str]]) -> None:
    root, heads = repo
    forge = FakeForge({'alpha': {**heads, 'pr/unfetched': 'e' * 40}})
    with pytest.raises(RootsUnread, match=r'alpha: eeeeeeeeeeee is not in the local checkout.*fetch origin'):
        report({'alpha': root}, forge, FakeStore(STORE), now=NOW)


def test_the_git_forge_reads_heads_and_refuses_an_empty_answer() -> None:
    def answering(stdout: str, code: int = 0) -> Callable[..., subprocess.CompletedProcess[str]]:
        def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
            assert argv[-3:] == ['ls-remote', '--heads', 'origin']
            return subprocess.CompletedProcess(argv, code, stdout, '')

        return run

    sha = '1' * 40
    heads = oraclegc.GitForge(run=answering(f'{sha}\trefs/heads/pr/x\n')).heads('alpha', Path())
    assert heads == {'pr/x': sha}
    with pytest.raises(RootsUnread, match='alpha: the forge listed no branches'):
        oraclegc.GitForge(run=answering('fatal: repository not found\n', 128)).heads('alpha', Path())


def test_there_is_no_delete_verb() -> None:
    with pytest.raises(SystemExit):
        oraclegc.main(['delete'])
    assert not any(hasattr(oraclegc, n) for n in ('delete', 'apply', 'prune'))


GOLDEN = 'e' * 64
SAMPLES = [_row(GOLDEN, 5, 2)]
FIELD = oraclegc.Pattern('cases/**/*.toml', 'sha256')


@pytest.fixture
def frozen(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A repo naming GOLDEN only by a ``sha256 = ...`` field of a cases TOML (an inline table), no lock."""
    root = tmp_path / 'frozen'
    root.mkdir()
    _git(root, 'init', '-q')
    sha = _commit(root, {'cases/m/golden.toml': f'[source]\nref = {{ sha256 = "{GOLDEN}" }}\n', 'note.toml': ''})
    return root, {'main': sha}


def test_a_field_named_golden_is_kept_when_the_family_declares_it(frozen: tuple[Path, dict[str, str]]) -> None:
    root, heads = frozen
    found = report({'frozen': root}, FakeForge({'frozen': heads}), FakeStore(SAMPLES), now=NOW,
                   family={'frozen': (FIELD,)})  # fmt: skip
    assert found.unreferenced == ()
    assert found.referenced == 1


def test_a_field_named_golden_is_reported_when_undeclared(frozen: tuple[Path, dict[str, str]]) -> None:
    root, heads = frozen
    found = report({'frozen': root}, FakeForge({'frozen': heads}), FakeStore(SAMPLES), now=NOW)
    assert [u.stored.sha256 for u in found.unreferenced] == [GOLDEN]


def test_a_repo_declares_its_own_roots_per_branch(tmp_path: Path) -> None:
    root = tmp_path / 'own'
    root.mkdir()
    _git(root, 'init', '-q')
    own = '[tool.dev_lab.oraclegc]\nroots = [{ glob = "**/*.toml", key = "golden" }]\n'
    sha = _commit(root, {'pyproject.toml': own, 'golden.toml': f'golden = "{GOLDEN}"\n'})
    found = report({'own': root}, FakeForge({'own': {'pr/x': sha}}), FakeStore(SAMPLES), now=NOW)
    assert found.unreferenced == ()


@pytest.mark.parametrize(
    'table',
    [
        {'roots': [{'glob': 'cases/**/*.toml'}]},
        {'roots': [{'glob': '../x/*.toml', 'key': 'sha256'}]},
        {'roots': [{'glob': '*.toml', 'key': 'sha 256'}]},
        {'roots': 'cases/**/*.toml'},
        {'root': []},
    ],
)
def test_a_malformed_pattern_is_refused(table: object) -> None:
    with pytest.raises(oraclegc.PatternRefused, match='family'):
        oraclegc.patterns_of(table, 'family')


def test_a_malformed_own_declaration_aborts_the_report_by_name(tmp_path: Path) -> None:
    root = tmp_path / 'bad'
    root.mkdir()
    _git(root, 'init', '-q')
    sha = _commit(root, {'pyproject.toml': '[tool.dev_lab.oraclegc]\nroots = [{ glob = "*.toml" }]\n'})
    store = FakeStore(SAMPLES)
    with pytest.raises(RootsUnread, match=r'bad@.*\[tool.dev_lab.oraclegc\] roots'):
        report({'bad': root}, FakeForge({'bad': {'main': sha}}), store, now=NOW)
    assert store.asked == 0


def test_the_family_table_is_read_from_the_oraclegc_section() -> None:
    section = {'repos': {'frozen': {'roots': [{'glob': 'cases/**/*.toml', 'key': 'sha256'}]}}}
    assert oraclegc.family_patterns(section) == {'frozen': (FIELD,)}
    assert oraclegc.family_patterns({}) == {}
    with pytest.raises(oraclegc.PatternRefused, match=r'\[oraclegc.repos\] frozen'):
        oraclegc.family_patterns({'repos': {'frozen': {'roots': [{'key': 'sha256'}]}}})
    with pytest.raises(oraclegc.PatternRefused, match='holds only repos'):
        oraclegc.family_patterns({'roots': []})
