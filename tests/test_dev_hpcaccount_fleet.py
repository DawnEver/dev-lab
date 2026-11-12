"""``hpcaccount deploy-fleet``: each declared account on ITS declared host, one detached ssh and one log each."""

from __future__ import annotations

from pathlib import Path

from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV
from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount.division import load_division
from dev_lab.dev.hpcaccount.fleet import _READ_DEPLOY, Target, declared_target, deploy_fleet, remote_argv
from dev_lab.dev.hpcaccount.spec import DEFAULT_ROOT

_HOSTS = ('login01.example', 'login02.example')
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='acct'),
    Grant(user='carol', hosts=_HOSTS, slurm_account='acct'),
)

#: What each account's own machine file declares, as ``sed`` prints its [deploy] table (and the next header).
_DEPLOY = {
    'alice': (
        '[deploy]\nhost = "login02.example"\nroot = "src"\nrepos = [\n  { name = "dev-lab" },\n]\n[[hpc.grant]]\n'
    ),
    'bob': '[deploy]\nhost = "login01.example"\nroot = "work"\n',
    'carol': '',
}


def _run(
    tmp_path: Path, accounts: tuple[str, ...] = (), deploy: dict[str, str] = _DEPLOY
) -> tuple[int, list[list[str]], list[str]]:
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        _FLEET,
        accounts,
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda grant: lambda _cmd, _stdin=None: deploy[grant.user],
        launch=lambda argv, _log: started.append(list(argv)),
    )
    return code, started, said


def test_each_account_deploys_on_its_own_declared_host(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path, ('alice', 'bob'))
    assert code == 0
    assert [argv[5] for argv in started] == ['alice@login02.example', 'bob@login01.example']
    assert 'cd ~/work/dev-lab' in started[1][-1], "bob's declared root"
    assert {p.name for p in tmp_path.rglob('*.log')} == {'alice.log', 'bob.log'}
    assert not any('refused' in line for line in said)


def test_an_account_with_no_declared_host_is_refused_and_the_rest_deploy(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path)
    assert code == 2
    assert [argv[5] for argv in started] == ['alice@login02.example', 'bob@login01.example']
    assert any(line.startswith('carol: refused') and '[deploy] host' in line for line in said)


def test_a_declared_host_outside_the_grant_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a machine file naming a host the grant does not is never ssh'd to."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "elsewhere.example"\n'})
    assert code == 2
    assert started == []
    assert any('not a login host' in line for line in said)


def test_an_undeclared_account_is_refused_and_nothing_starts(tmp_path: Path) -> None:
    """PLANTED CONTROL: one stranger among declared names refuses the whole run."""
    code, started, _ = _run(tmp_path, ('alice', 'mallory'))
    assert code == 2
    assert started == []


def test_the_workstations_role_and_table_are_passed_to_each_deploy() -> None:
    """User rulings 2026-11-09: the workstation is the source of the division."""
    division = load_division({'grant': [{'user': 'alice', 'role': 'research'}, {'user': 'bob'}]})
    argv = remote_argv(_FLEET[0], Target('login02.example', 'src'), division)
    assert '--fleet-role research --role-table ' in argv[-1]
    assert '{"read_only": true, "serves": false}' in argv[-1]
    assert '--fleet-role' not in remote_argv(_FLEET[1], Target('login01.example', 'work'), division)[-1]


def test_a_grant_role_the_table_does_not_name_is_refused_before_any_ssh(tmp_path: Path) -> None:
    """PLANTED CONTROL: the account whose role the table names still deploys."""
    division = load_division(
        {'grant': [{'user': 'alice', 'role': 'research'}, {'user': 'bob', 'role': 'gone'}], 'roles': {'research': {}}}
    )
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        _FLEET,
        ('alice', 'bob'),
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda grant: lambda _cmd, _stdin=None: _DEPLOY[grant.user],
        launch=lambda argv, _log: started.append(list(argv)),
        division=division,
    )
    assert code == 2
    assert [argv[5] for argv in started] == ['alice@login02.example']
    assert any(line.startswith('bob:') and "'gone'" in line for line in said)


def test_the_remote_runs_the_accounts_own_deploy_never_prompting() -> None:
    argv = remote_argv(_FLEET[0], Target('login02.example', 'src'))
    assert argv[:3] == ['ssh', '-o', 'BatchMode=yes']
    assert 'cd ~/src/dev-lab && .venv/bin/python -m dev_lab.dev.hpcaccount deploy' in argv[-1]
    assert '--grant-table' in argv[-1], 'the declared slice is the one source of the grant the deploy writes'


def test_an_account_with_two_grants_is_refused_rather_than_one_silently_kept(tmp_path: Path) -> None:
    said: list[str] = []
    twice = (*_FLEET, Grant(user='alice', hosts=('other.example',), slurm_account='acct'))
    code = deploy_fleet(
        twice,
        (),
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda grant: lambda _cmd, _stdin=None: _DEPLOY[grant.user],
        launch=lambda _argv, _log: None,
    )
    assert code == 2
    assert any("['alice'] hold more than one" in line for line in said)


def test_a_declared_short_host_resolves_to_its_grant_login_host(tmp_path: Path) -> None:
    """A machine file's ``login01`` IS the grant's ``login01.example``: the full name is what is dialled."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login01"\n'})
    assert code == 0
    assert [argv[5] for argv in started] == ['bob@login01.example']
    assert not any('refused' in line for line in said)


def test_a_short_host_matching_no_grant_label_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a bare label that is no grant host's first label is still refused."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login"\n'})
    assert code == 2
    assert started == []
    assert any('not a login host' in line for line in said)


def test_a_short_host_two_grant_hosts_share_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a label naming two login hosts names neither, so it is refused, never the first kept."""
    twins = (Grant(user='bob', hosts=('login01.a.example', 'login01.b.example'), slurm_account='acct'),)
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        twins,
        ('bob',),
        home=tmp_path,
        dry_run=False,
        say=said.append,
        connect=lambda _grant: lambda _cmd, _stdin=None: '[deploy]\nhost = "login01"\n',
        launch=lambda argv, _log: started.append(list(argv)),
    )
    assert code == 2
    assert started == []
    assert any('ambiguous' in line for line in said)


def test_an_undeclared_root_is_the_forge_home_never_home_src() -> None:
    """User rulings 2026-10-26 and 2026-11-06: ~/src is retired; a served checkout lives in the forge home.

    PLANTED CONTROL: a declared root is still honoured as given.
    """
    assert DEFAULT_ROOT == '.local/share/lab-forge/repos'
    assert DEFAULT_ROOT.split('/')[0] != 'src'
    assert Target('login02.example', 'elsewhere').root == 'elsewhere'


def test_the_fleet_view_prints_each_accounts_declared_role(tmp_path: Path) -> None:
    """User ruling 2026-11-06: the role is read from the account's own [deploy]; PLANTED CONTROL: bob declares none."""
    deploy = {**_DEPLOY, 'alice': '[deploy]\nhost = "login02.example"\nrole = "research"\n'}
    code, _started, said = _run(tmp_path, ('alice', 'bob'), deploy)
    assert code == 0
    assert any(line.startswith('alice (research): started') for line in said)
    assert any(line.startswith('bob (role undeclared): started') for line in said)


def test_the_deploy_table_is_read_where_the_accounts_own_config_path_resolves() -> None:
    """Measured 2026-11-10: a retired ``~/.config/lab-commons`` path refused two deployed accounts."""
    assert '${LAB_COMMONS_CONFIG:-${' in _READ_DEPLOY
    assert _READ_DEPLOY.startswith(f'f="${{{CONFIG_ENV}:-${{{HOME_ENV}:-$HOME/')
    assert '.config/lab-commons' not in _READ_DEPLOY


def test_a_refusal_names_the_file_it_looked_in() -> None:
    grant = Grant(user='carol', hosts=_HOSTS, slurm_account='acct')
    why = declared_target(grant, lambda _cmd, _stdin=None: '# /srv/u/machine/config.toml\n')
    assert why == 'carol: refused -- no [deploy] host in /srv/u/machine/config.toml; deploy it once by hand'
