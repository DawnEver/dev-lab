"""``hpcaccount backup`` / ``backup-fleet``: crontab and machine file saved and restored; a fleet filter required."""

from __future__ import annotations

from pathlib import Path

from _hpcaccount_fakes import MACHINE, MARKED, home_of, tools_of
from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount import backup as account_backup
from dev_lab.dev.hpcaccount.fleet import ConfigSource
from dev_lab.dev.hpcaccount.steps import Tools


def _written(home: Path) -> Path:
    (target,) = home.glob('.cache/dev-lab/*/*/*/backup/*')
    return target


def test_the_backup_holds_the_full_crontab_and_the_machine_file_only(tmp_path: Path) -> None:
    home, machine = home_of(tmp_path)
    cron = '0 1 * * * echo mine\n' + MARKED
    (tmp_path / 'crontab.txt').write_text(cron, encoding='utf-8')
    assert account_backup.backup(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 0
    target = _written(home)
    assert sorted(f.name for f in target.iterdir()) == ['crontab.txt', 'machine-config.toml']
    assert (target / 'crontab.txt').read_text(encoding='utf-8') == cron
    assert (target / 'machine-config.toml').read_text(encoding='utf-8') == MACHINE
    assert (tmp_path / 'crontab.txt').read_text(encoding='utf-8') == cron


def test_a_research_account_with_no_crontab_is_still_backed_up(tmp_path: Path) -> None:
    home, machine = home_of(tmp_path)
    assert account_backup.backup(['--config', str(machine)], home=home, tools=tools_of(tmp_path)) == 0
    assert (_written(home) / 'crontab.txt').read_text(encoding='utf-8') == ''


def test_an_unreadable_crontab_writes_nothing_and_exits_2(tmp_path: Path) -> None:
    home, machine = home_of(tmp_path)
    assert account_backup.backup(['--config', str(machine)], home=home, tools=tools_of(tmp_path, 'broken')) == 2
    assert not (home / '.cache').exists()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    home, machine = home_of(tmp_path)
    assert account_backup.backup(['--config', str(machine), '--dry-run'], home=home, tools=tools_of(tmp_path)) == 0
    assert not (home / '.cache').exists()


def _backed_up(tmp_path: Path, cron: str) -> tuple[Path, Path, Tools]:
    home, machine = home_of(tmp_path)
    (tmp_path / 'crontab.txt').write_text(cron, encoding='utf-8')
    tools = tools_of(tmp_path)
    assert account_backup.backup(['--config', str(machine)], home=home, tools=tools) == 0
    return home, machine, tools


def test_restore_puts_back_the_marked_lines_and_keeps_a_new_user_line(tmp_path: Path) -> None:
    home, machine, tools = _backed_up(tmp_path, '0 1 * * * mine\n' + MARKED)
    (tmp_path / 'crontab.txt').write_text('0 1 * * * mine\n0 2 * * * new\n', encoding='utf-8')
    machine.write_text('# wiped by maintenance\n', encoding='utf-8')
    assert account_backup.backup(['--config', str(machine), '--restore', 'latest'], home=home, tools=tools) == 0
    assert (tmp_path / 'crontab.txt').read_text(encoding='utf-8') == '0 1 * * * mine\n0 2 * * * new\n' + MARKED
    assert machine.read_text(encoding='utf-8') == MACHINE
    assert any(home.glob('.cache/dev-lab/*/*/*/devhost/config.toml.*'))


def test_restore_puts_back_the_whole_crontab_when_the_users_lines_were_lost(tmp_path: Path) -> None:
    home, machine, tools = _backed_up(tmp_path, '0 1 * * * mine\n' + MARKED)
    (tmp_path / 'crontab.txt').unlink()
    assert account_backup.backup(['--config', str(machine), '--restore', 'latest'], home=home, tools=tools) == 0
    assert (tmp_path / 'crontab.txt').read_text(encoding='utf-8') == '0 1 * * * mine\n' + MARKED


def test_restore_of_an_unknown_stamp_is_refused(tmp_path: Path) -> None:
    home, machine, tools = _backed_up(tmp_path, '0 1 * * * mine\n')
    assert account_backup.backup(['--config', str(machine), '--restore', 'nope'], home=home, tools=tools) == 2


_HOSTS = ('login01.example',)
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='a', cluster_name='c1'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='a', cluster_name='c2'),
    Grant(user='rita', hosts=_HOSTS, slurm_account='a', cluster_name='c1'),
)
_ROLES = {'alice': 'verification', 'bob': 'verification', 'rita': 'research'}


def _source(tmp_path: Path) -> ConfigSource:
    clone = tmp_path / 'src'
    (clone / 'hosts').mkdir(parents=True)
    rows = (f'[[hpc.grant]]\nuser = "{g.user}"\ncluster = "{g.cluster_name}"\nslurm_account = "a"\n' for g in _FLEET)
    (clone / 'family.toml').write_text(''.join(rows), encoding='utf-8')
    for g in _FLEET:
        layer = f'[deploy]\nhost = "login01.example"\nroot = "repos"\nrole = "{_ROLES[g.user]}"\n'
        (clone / 'hosts' / f'{g.cluster_name}-{g.user}.toml').write_text(layer, encoding='utf-8')
    return ConfigSource(clone, 'https://forge.example/config.git')


def fleet(
    tmp_path: Path, accounts: tuple[str, ...], clusters: tuple[str, ...], *, verb: str = 'backup', ci: bool = False
) -> tuple[int, list[str], list[str]]:
    """Run a fleet verb over :data:`_FLEET`; its code, the started ``dest command`` lines and what it said."""
    started: list[str] = []
    said: list[str] = []
    serving = (lambda target: target.role == 'verification') if ci else None
    code = account_backup.backup_fleet(
        _FLEET, accounts, clusters, home=tmp_path, source=_source(tmp_path), say=said.append, verb=verb,
        serving_only=serving, launch=lambda dest, command, _log: started.append(f'{dest} {command}'),
    )  # fmt: skip
    return code, started, said


def test_a_cluster_filter_backs_up_only_that_clusters_accounts(tmp_path: Path) -> None:
    code, started, _ = fleet(tmp_path, (), ('c1',))
    assert code == 0
    assert [line.split()[0] for line in started] == ['alice@login01.example', 'rita@login01.example']
    assert all('dev_lab.dev.hpcaccount backup' in line for line in started)


def test_no_filter_is_refused_and_nothing_starts(tmp_path: Path) -> None:
    code, started, said = fleet(tmp_path, (), ())
    assert (code, started) == (2, [])
    assert '--cluster or --account' in said[0]


def test_an_undeclared_cluster_is_refused_by_name(tmp_path: Path) -> None:
    code, started, said = fleet(tmp_path, (), ('nowhere',))
    assert (code, started) == (2, [])
    assert 'nowhere' in said[0]


def test_ci_pause_fleet_skips_a_research_account_of_the_cluster(tmp_path: Path) -> None:
    code, started, said = fleet(tmp_path, (), ('c1',), verb='ci-pause', ci=True)
    assert code == 0
    assert [line.split()[0] for line in started] == ['alice@login01.example']
    assert any('rita' in line and 'no CI cron by design' in line for line in said)


def test_ci_pause_fleet_refuses_a_research_account_named_explicitly(tmp_path: Path) -> None:
    code, started, said = fleet(tmp_path, ('rita',), (), verb='ci-pause', ci=True)
    assert (code, started) == (2, [])
    assert 'no CI cron by design' in said[0]
