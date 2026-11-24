"""BASELINES LIVE IN THE RUN STORE (H2, 2026-11-24): the repo keeps one lock, a rewrite quotes its numbers."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import baselines
from dev_lab.dev.baselines import Row

_GIT = shutil.which('git') or 'git'


class _Store:
    """A planted content-addressed store: the same put/get contract as the run store's."""

    name = 'planted'

    def __init__(self, where: Path) -> None:
        self.where = where
        self.where.mkdir(parents=True, exist_ok=True)

    def put(self, path: Path) -> str:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        shutil.copyfile(path, self.where / sha)
        return sha

    def get(self, sha256: str, dest: Path) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.where / sha256, dest)
        return dest


def _row(name: str = 'torque', sha: str = 'a' * 64) -> Row:
    return Row(test='tests/test_x.py::test_torque', sha256=sha, name=name, command='produce x', source_sha='f' * 40)


def test_a_lock_round_trips_as_one_json_row_per_baseline(tmp_path: Path) -> None:
    lock = tmp_path / 'baselines.lock'
    rows = [_row('b'), _row('a')]
    baselines.write_lock(lock, rows)
    assert baselines.read_lock(lock) == sorted(rows, key=lambda row: row.name)
    assert len(lock.read_text(encoding='utf-8').splitlines()) == 2


@pytest.mark.parametrize(
    ('text', 'named'),
    [
        ('{"test": "t", "name": "x"}\n', 'sha256'),
        ('not json\n', 'line 1'),
        ('{"test": "t", "sha256": "zz", "name": "x", "command": "c", "source_sha": "s"}\n', 'sha256'),
    ],
)
def test_a_malformed_lock_row_is_refused_by_line(tmp_path: Path, text: str, named: str) -> None:
    lock = tmp_path / 'baselines.lock'
    lock.write_text(text, encoding='utf-8')
    with pytest.raises(baselines.LockRefused, match=named):
        baselines.read_lock(lock)


def test_put_then_get_reads_through_the_local_cache(tmp_path: Path) -> None:
    store = _Store(tmp_path / 'oracle')
    source = tmp_path / 'torque.csv'
    source.write_text('1,2\n', encoding='utf-8')
    root = tmp_path / 'repo'
    root.mkdir()
    row = baselines.put(root, source, name='torque', test='t', command='c', source_sha='s' * 40, store=store)
    assert baselines.read_lock(root / baselines.LOCK) == [row]
    got = baselines.get(root, 'torque', store=store)
    assert got == root / 'output' / 'cache' / 'planted' / 'baselines' / row.sha256
    assert got.read_text(encoding='utf-8') == '1,2\n'
    (store.where / row.sha256).unlink()  # the cache answers without the store now
    assert baselines.get(root, 'torque', store=store).read_text(encoding='utf-8') == '1,2\n'


def test_a_cached_file_that_no_longer_hashes_is_refetched_never_served(tmp_path: Path) -> None:
    """PLANTED CONTROL: a tampered cache entry is a miss."""
    store = _Store(tmp_path / 'oracle')
    source = tmp_path / 'torque.csv'
    source.write_text('1,2\n', encoding='utf-8')
    root = tmp_path / 'repo'
    root.mkdir()
    row = baselines.put(root, source, name='torque', test='t', command='c', source_sha='s' * 40, store=store)
    cached = baselines.get(root, 'torque', store=store)
    cached.write_text('9,9\n', encoding='utf-8')
    assert baselines.get(root, 'torque', store=store).read_text(encoding='utf-8') == '1,2\n'
    assert row.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_an_unknown_baseline_is_refused_naming_the_lock(tmp_path: Path) -> None:
    with pytest.raises(baselines.LockRefused, match=r'nope.*baselines\.lock'):
        baselines.get(tmp_path, 'nope', store=_Store(tmp_path / 'o'))


def test_a_rewrite_must_quote_old_and_new_numbers() -> None:
    old, new = [_row(sha='a' * 64)], [_row(sha='b' * 64)]
    assert baselines.rewritten(old, new) == ('torque',)
    refused = baselines.unquoted(baselines.rewritten(old, new), 'refresh the torque golden')
    assert refused == ('torque',)
    quoted = 'refresh\n\nbaseline torque: old 0.0213 new 0.0108\n'
    assert baselines.unquoted(baselines.rewritten(old, new), quoted) == ()


def test_an_added_row_is_not_a_rewrite() -> None:
    """PLANTED CONTROL: a new baseline has no old number to quote."""
    assert baselines.rewritten([], [_row()]) == ()


@pytest.mark.parametrize(
    ('tracked', 'refused'),
    [
        (['tests/test_a.py', 'tests/baselines.lock', 'tests/crate/Cargo.toml', 'tests/x.rs'], []),
        (
            ['tests/test_a.py', 'tests/goldens/torque.csv', 'tests/data/mesh.npz'],
            ['tests/data/mesh.npz', 'tests/goldens/torque.csv'],
        ),
    ],
)
def test_a_tracked_data_file_under_tests_is_refused_naming_the_door(tracked: list[str], refused: list[str]) -> None:
    assert baselines.data_files(tracked) == refused


def _git(root: Path, *args: str) -> None:
    subprocess.run([_GIT, '-C', str(root), *args], check=True, capture_output=True, timeout=60)


def _commit(root: Path, rows: list[Row], message: str) -> str:
    baselines.write_lock(root / baselines.LOCK, rows)
    _git(root, 'add', '-A')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', message)
    return subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', 'HEAD'], check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


def test_verify_refuses_an_unquoted_rewrite_and_passes_a_quoted_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The door end to end on a planted repo: both sides of the rewrite rule, and the tracked-data refusal."""
    _git(tmp_path, 'init', '-q')
    monkeypatch.chdir(tmp_path)
    _commit(tmp_path, [_row(sha='a' * 64)], 'add the torque baseline')
    silent = _commit(tmp_path, [_row(sha='b' * 64)], 'refresh torque')
    assert baselines.main(['verify', '--commit', silent]) == 1
    assert 'baseline torque: old <number> new <number>' in capsys.readouterr().err
    quoted = _commit(tmp_path, [_row(sha='c' * 64)], 'refresh torque\n\nbaseline torque: old 0.0213 new 0.0108')
    assert baselines.main(['verify', '--commit', quoted]) == 0
    (tmp_path / 'tests' / 'golden.csv').write_text('1\n', encoding='utf-8')
    _git(tmp_path, 'add', 'tests/golden.csv')
    assert baselines.main(['verify']) == 1
    assert (
        f'tests/golden.csv: a tracked data file under tests/ -- move it to the run store with {baselines.DOOR} put'
        in (capsys.readouterr().err)
    )


def test_the_commit_msg_row_judges_the_staged_lock_before_the_commit_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """BASELINE-REWRITE-QUOTED at commit time: a staged rewrite is refused unquoted and admitted quoted."""
    _git(tmp_path, 'init', '-q')
    monkeypatch.chdir(tmp_path)
    _commit(tmp_path, [_row(sha='a' * 64)], 'add the torque baseline')
    baselines.write_lock(tmp_path / baselines.LOCK, [_row(sha='b' * 64)])
    _git(tmp_path, 'add', '-A')
    message = tmp_path / 'MSG'
    message.write_text('refresh torque\n', encoding='utf-8')
    assert baselines.main(['check-message', str(message)]) == 1
    assert 'BASELINE-REWRITE-QUOTED: this commit rewrites baseline' in capsys.readouterr().err
    message.write_text('refresh torque\n\nbaseline torque: old 0.0213 new 0.0108\n', encoding='utf-8')
    assert baselines.main(['check-message', str(message)]) == 0


def test_the_commit_msg_row_is_registered() -> None:
    base = (Path(baselines.__file__).parent / 'githooks' / 'base.toml').read_text(encoding='utf-8')
    assert 'run = ["python", "-m", "dev_lab.dev.baselines", "check-message"]' in base
