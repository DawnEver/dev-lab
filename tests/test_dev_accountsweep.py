"""``dev_lab.dev.accountsweep`` -- the caller's retention rules, streamed to an account too full to update its kit.

MEASURED 2026-11-22: an account at its file quota could not update its kit, so the fleet retention ran the kit's OLD
rules there and freed ten files. The rules now travel with the caller: one standard-library file on the account
interpreter's stdin, nothing written there. PLANTED CONTROLS: an interpreter that can import NOTHING of the kit still
runs them; the environment the pointer names, one a live process executes from, a research directory and the cache
of a running ``uv`` are kept.
"""

from __future__ import annotations

import ast
import errno
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dev_lab.dev import accountsweep
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.hpcaccount.storage import SWEEP_SOURCE, sweep_spec

if os.name == 'nt':
    import _winapi


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:  # Windows without the symlink privilege: a junction, as the pointer is there
        _winapi.CreateJunction(str(target), str(link))


_MADE = (
    'ci/trees/abc', 'research/ci', 'lab/dev-lab', 'lab/repos/r/.venvs/current/bin', 'lab/repos/r/.venvs/half-built/lib',
    'lab/repos/r/.venvs/in-use/bin', 'lab/cache/uv/.tmpAb12/x', 'lab/cache/uv/wheels-v1', 'lab/envs/k',
)  # fmt: skip


def _account(tmp_path: Path) -> tuple[Path, Path, dict]:
    """A full account: old copies, a half-built and a current environment, uv's leftovers, a research directory."""
    home, root = tmp_path / 'home', tmp_path / 'home' / 'lab'
    for made in _MADE:
        (home / made).mkdir(parents=True)
    _link(root / 'repos' / 'r' / '.venv', root / 'repos' / 'r' / '.venvs' / 'current')
    return home, root, sweep_spec(Target('login01.example', root.as_posix()), apply=False)


#: A process table that reads, and lists nothing that references a candidate.
_NOBODY: list[dict] = []


def _sweep(
    home: Path, root: Path, spec: dict, *, cron: str | None = '', live: list[dict] | None = _NOBODY
) -> list[str]:
    said: list[str] = []
    accountsweep.sweep(spec, home=home, root=root, say=said.append, cron=cron, live=live)
    return said


def test_the_streamed_file_imports_the_standard_library_alone() -> None:
    tree = ast.parse(SWEEP_SOURCE)
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    }
    assert {str(name).split('.')[0] for name in imported} <= sys.stdlib_module_names | {'__future__'}


def test_an_interpreter_that_cannot_import_the_kit_still_runs_the_callers_rules(tmp_path: Path) -> None:
    """The planted full account: ``python -I -`` in an empty directory -- no kit, no site -- fed the source on stdin."""
    home, _root, spec = _account(tmp_path)
    (tmp_path / 'empty').mkdir()
    env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home)}
    done = subprocess.run(
        [sys.executable, '-I', '-', json.dumps(spec)], input=SWEEP_SOURCE, capture_output=True, text=True,
        encoding='utf-8', cwd=tmp_path / 'empty', env=env, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert (home / 'ci').as_posix() in done.stdout, 'the old copy was judged by the streamed rules'
    assert '[retention] would delete ' in done.stdout.splitlines()[-1]
    assert (home / 'ci' / 'trees' / 'abc').is_dir(), 'a dry run deletes nothing'
    assert list((tmp_path / 'empty').iterdir()) == [], 'nothing is written'


def test_the_three_rules_are_a_dry_run_then_delete_on_apply(tmp_path: Path) -> None:
    home, root, spec = _account(tmp_path)
    said = _sweep(home, root, spec)
    assert '[retention] would delete old-copy: 2 paths, 0.0 MB, 4 files' in said
    assert '[retention] would delete uv-cache-tmp: 1 paths, 0.0 MB, 2 files' in said
    assert '[retention] would delete venv-not-current: 2 paths, 0.0 MB, 4 files' in said
    assert said[-1] == '[retention] would delete 5 paths, 0.0 MB, 10 files'
    assert (root / 'repos/r/.venvs/half-built').is_dir()
    said = _sweep(home, root, spec | {'apply': True})
    assert said[-1] == '[retention] deleted 5 paths, 0.0 MB, 10 files'
    for gone in (
        'ci',
        'lab/dev-lab',
        'lab/repos/r/.venvs/half-built',
        'lab/repos/r/.venvs/in-use',
        'lab/cache/uv/.tmpAb12',
    ):
        assert not (home / gone).exists(), gone
    for kept in ('research/ci', 'lab/repos/r/.venvs/current/bin', 'lab/cache/uv/wheels-v1', 'lab/envs/k'):
        assert (home / kept).is_dir(), f'{kept} is none of the three rules'


def test_what_something_references_is_kept_by_name(tmp_path: Path) -> None:
    home, root, spec = _account(tmp_path)
    in_use = root / 'repos' / 'r' / '.venvs' / 'in-use'
    live = [
        {'pid': 7, 'exe': str(in_use / 'bin' / 'python'), 'cwd': str(home), 'argv': ['python', '-m', 'app']},
        {'pid': 8, 'exe': '/usr/local/bin/uv', 'cwd': str(home), 'argv': ['uv', 'sync']},
    ]
    said = _sweep(home, root, spec | {'apply': True}, cron='*/5 * * * * cd ~/ci && ./tick\n', live=live)
    assert f'[retention] kept (old-copy): {(home / "ci").as_posix()} -- a crontab line still names it' in said
    assert f'[retention] kept (venv-not-current): {in_use.as_posix()} -- a live process still uses it: pid 7' in said
    tmp = (root / 'cache' / 'uv' / '.tmpAb12').as_posix()
    assert f'[retention] kept (uv-cache-tmp): {tmp} -- a uv process is running: its cache is in use' in said
    assert in_use.is_dir()
    assert (home / 'ci').is_dir()
    assert not (root / 'repos/r/.venvs/half-built').exists(), 'the unreferenced one beside them went'
    assert said[-1] == '[retention] deleted 2 paths, 0.0 MB, 3 files'


def test_an_unreadable_crontab_or_process_table_keeps_everything(tmp_path: Path) -> None:
    home, root, spec = _account(tmp_path)
    for unread in ({'cron': None}, {'live': None}):
        said = _sweep(home, root, spec | {'apply': True}, **unread)
        assert said[-1] == '[retention] deleted 0 paths, 0.0 MB, 0 files'
        assert sum('cannot be read' in line or 'a uv process is running' in line for line in said) == 5


def test_an_unremovable_entry_is_named_and_kept_and_the_pass_ends_with_its_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED 2026-11-22: one entry the account could not chmod killed the pass with a traceback, no summary."""
    home, root, spec = _account(tmp_path)
    old = home / 'ci' / 'trees' / 'abc'
    for name in ('a.log', 'locked.log', 'b.log'):
        (old / name).write_text('x', encoding='utf-8')
    real = os.unlink

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        if str(path).endswith('locked.log'):
            raise PermissionError(errno.EPERM, 'Operation not permitted', str(path))
        real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, 'unlink', refuse)
    said = _sweep(home, root, spec | {'apply': True})
    assert f'[retention] kept {old.as_posix()} -- cannot remove 1 entries: Operation not permitted' in said
    assert sorted(p.name for p in old.iterdir()) == ['locked.log'], 'the rest of the copy went'
    assert not (root / 'repos' / 'r' / '.venvs' / 'half-built').exists(), 'every other rule ran after it'
    assert said[-1].startswith('[retention] deleted '), 'the pass ends with its summary'
    assert said[-1].endswith('; kept 1 entries that cannot be removed')
    rows = [json.loads(line) for line in said if line.startswith('{')]
    copy = next(row for row in rows if row['path'] == str(home / 'ci'))
    assert copy['files'] >= 1
    assert (home / 'ci').exists(), 'counted only what went: the kept file and its parents stay'


def test_planted_control_a_removable_copy_is_removed_whole(tmp_path: Path) -> None:
    home, root, spec = _account(tmp_path)
    (home / 'ci' / 'trees' / 'abc' / 'a.log').write_text('x', encoding='utf-8')
    said = _sweep(home, root, spec | {'apply': True})
    assert not (home / 'ci').exists()
    assert not any('cannot remove' in line for line in said)


def test_stale_cargo_registry_sources_go_and_a_fresh_crate_stays(tmp_path: Path) -> None:
    home, root, spec = _account(tmp_path)
    src = home / '.cargo' / 'registry' / 'src' / 'index-1'
    (src / 'old-1.0').mkdir(parents=True)
    (src / 'fresh-2.0').mkdir()  # PLANTED CONTROL: touched now
    os.utime(src / 'old-1.0', (0, 0))
    (home / '.cargo' / 'registry' / 'cache').mkdir()  # PLANTED CONTROL: the .crate cache is never named
    assert spec['cargo_rule'] == 'cargo-registry-src'
    _sweep(home, root, spec | {'apply': True})
    assert sorted(p.name for p in src.iterdir()) == ['fresh-2.0']
    assert (home / '.cargo' / 'registry' / 'cache').is_dir()


def _locked(monkeypatch: pytest.MonkeyPatch) -> None:
    real = os.unlink

    def refuse(path: object, *args: object, **kwargs: object) -> None:
        if Path(str(path)).name.startswith('locked'):
            raise PermissionError(errno.EPERM, 'Operation not permitted', str(path))
        real(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, 'unlink', refuse)


def test_many_unremovable_entries_under_one_directory_are_one_line_with_their_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MEASURED 2026-11-23: 206,412 kept lines, all under ONE directory, drowned the output."""
    home, root, spec = _account(tmp_path)
    run = home / 'ci' / 'trees' / 'abc' / 'out'
    (run / 'deep').mkdir(parents=True)
    for n in range(40):
        (run / f'locked-{n}.log').write_text('x', encoding='utf-8')
        (run / 'deep' / f'locked-{n}.log').write_text('x', encoding='utf-8')
    _locked(monkeypatch)
    said = [line for line in _sweep(home, root, spec | {'apply': True}) if 'cannot remove' in line]
    assert said == [f'[retention] kept {run.as_posix()} -- cannot remove 80 entries: Operation not permitted']


def test_planted_control_two_separate_directories_are_two_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, root, spec = _account(tmp_path)
    first, second = home / 'ci' / 'trees' / 'abc' / 'one', home / 'ci' / 'trees' / 'abc' / 'two'
    for where in (first, second):
        where.mkdir(parents=True)
        for n in range(3):
            (where / f'locked-{n}.log').write_text('x', encoding='utf-8')
    _locked(monkeypatch)
    said = _sweep(home, root, spec | {'apply': True})
    assert [line for line in said if 'cannot remove' in line] == [
        f'[retention] kept {first.as_posix()} -- cannot remove 3 entries: Operation not permitted',
        f'[retention] kept {second.as_posix()} -- cannot remove 3 entries: Operation not permitted',
    ]
    assert said[-1].endswith('; kept 6 entries that cannot be removed')
