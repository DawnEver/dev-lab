"""``dev_lab.dev.oldcopies`` -- the account's retention removes what its old layout left behind (ruling 2026-11-22).

"Deleting is allowed -- deleting is the DEFAULT": the copies ``drift`` lists (ONE list, this module's) go by the
retention rule ``old-copy``, a dry run unless ``--apply``. PLANTED CONTROLS: a research directory in the home is
never one; a copy a crontab line names, a live process uses, this run works in, or that holds the declared root
is kept and named; an unreadable crontab keeps them all.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from lab_commons.hpc.layout import ROOT_VAR

from dev_lab.dev import oldcopies, retention
from dev_lab.dev.hpcaccount import drift
from dev_lab.dev.retentionplan import Plan


def _account(tmp_path: Path) -> tuple[Path, Path]:
    """A home and its declared root holding every old copy, the declared layout, and a research directory."""
    home, root = tmp_path / 'home', tmp_path / 'home' / 'lab'
    for old in (home / 'ci' / 'trees' / 'abc', home / '.local' / 'share' / 'lab-forge', home / 'src' / 'dev-lab'):
        old.mkdir(parents=True)
    for old in (root / 'dev-lab', root / 'src' / 'x', root / 'repos' / 'r', root / 'envs' / 'k'):
        old.mkdir(parents=True)
    (root / 'repos' / 'r' / '.venv-current').write_text('x', encoding='utf-8')
    (home / 'research' / 'ci').mkdir(parents=True)  # the user's own: never an old copy, whatever it is called
    (home / 'ci-notes').mkdir()
    return home, root


def _plan(home: Path, root: Path, **given: object) -> tuple[list[str], list[str]]:
    wanted = {'cwd': root / 'repos' / 'r', 'crontab': lambda: '', 'holders': lambda _copy: ()} | given
    doomed, kept = oldcopies.plan(home, root, **wanted)  # type: ignore[arg-type]
    return [d.path.relative_to(home).as_posix() for d in doomed], kept


def test_every_old_copy_goes_by_one_rule_and_nothing_else_does(tmp_path: Path) -> None:
    home, root = _account(tmp_path)
    going, kept = _plan(home, root)
    assert going == [
        '.local/share/lab-forge',
        'ci',
        'src/dev-lab',
        'lab/dev-lab',
        'lab/src',
        'lab/repos/r/.venv-current',
    ]
    assert kept == []
    listed = [line.rpartition(': ')[0] for line in drift.strays(home, root)]
    assert listed == [(home / one).as_posix() for one in going], 'drift reports the list retention deletes'


def test_a_referenced_old_copy_is_kept_by_name(tmp_path: Path) -> None:
    home, root = _account(tmp_path)
    commented = f'# cd {home.as_posix()}/src/dev-lab (a comment names nothing)'
    cron = f'*/5 * * * * cd ~/ci && ./tick\n{commented}\n@daily ~/ci-notes/x\n'
    live = SimpleNamespace(pid=7, executable='/usr/bin/python', command_line='python -m app')
    going, kept = _plan(
        home, root, cwd=root / 'dev-lab' / 'sub', crontab=lambda: cron,
        holders=lambda copy: (live,) if copy == root / 'src' else (),
    )  # fmt: skip
    assert going == ['.local/share/lab-forge', 'src/dev-lab', 'lab/repos/r/.venv-current']
    assert kept == [
        f'[retention] old copy kept: {(home / "ci").as_posix()} -- a crontab line still names it',
        f'[retention] old copy kept: {(root / "dev-lab").as_posix()} -- this retention runs from it',
        f'[retention] old copy kept: {(root / "src").as_posix()} -- a live process still uses it: pid 7 (app)',
    ]


def test_an_unreadable_crontab_and_a_root_inside_a_copy_keep_them(tmp_path: Path) -> None:
    home, root = _account(tmp_path)
    going, kept = _plan(home, root, crontab=lambda: None)
    assert going == []
    assert len(kept) == 6
    assert all('the crontab cannot be read' in line for line in kept)
    lives_in = home / 'src' / 'dev-lab'  # an account not yet moved: its root IS an old copy's place
    going, kept = _plan(home, lives_in)
    assert 'src/dev-lab' not in going
    assert (
        f'[retention] old copy kept: {lives_in.as_posix()} -- it holds the declared root: the account still lives in it'
        in kept
    )


def test_the_accounts_retention_is_a_dry_run_then_deletes_on_apply(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, root = _account(tmp_path)
    said: list[str] = []
    monkeypatch.setattr(Path, 'home', classmethod(lambda _cls: home))
    monkeypatch.chdir(root / 'repos' / 'r')
    monkeypatch.setenv(ROOT_VAR, root.as_posix())
    monkeypatch.setattr(retention, 'section', lambda _name: {})
    monkeypatch.setattr(retention, '_live_shas', set)
    monkeypatch.setattr(retention, 'read_usage', lambda *_a, **_k: None)
    monkeypatch.setattr(retention, '_plan_for', lambda *_a, **_k: Plan(()))
    monkeypatch.setattr(retention, '_crontab', lambda: '')
    monkeypatch.setattr(oldcopies, 'removal_holders', lambda _copy: ())
    monkeypatch.setattr(retention, 'emit', lambda line, **_k: said.append(line))
    assert retention.main(['--cluster']) == 0
    assert '[retention] would delete old-copy: 6 paths, 0.0 MB, 9 files' in said, said
    assert (home / 'ci' / 'trees' / 'abc').is_dir(), 'a dry run deletes nothing'
    assert retention.main(['--cluster', '--apply']) == 0
    assert any(line.startswith('[retention] deleted old-copy: 6 paths') for line in said), said
    gone = (home / 'ci', home / '.local/share/lab-forge', home / 'src/dev-lab', root / 'dev-lab', root / 'src')
    assert not any(path.exists() for path in gone)
    assert not (root / 'repos' / 'r' / '.venv-current').exists()
    for kept in (home / 'research' / 'ci', home / 'ci-notes', root / 'repos' / 'r', root / 'envs' / 'k'):
        assert kept.is_dir(), f'{kept} is no old copy'
