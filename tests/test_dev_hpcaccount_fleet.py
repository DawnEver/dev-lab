"""``hpcaccount deploy-fleet``: each declared account on ITS declared host, one detached ssh and one log each."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV
from lab_commons.hpc.grants import Grant

from dev_lab.dev.hpcaccount import deploy as account_deploy
from dev_lab.dev.hpcaccount.division import load_division
from dev_lab.dev.hpcaccount.fleet import (
    _READ_DEPLOY,
    ConfigSource,
    Target,
    declared_target,
    deploy_command,
    deploy_fleet,
    first_install,
    render_command,
)
from dev_lab.dev.hpcaccount.spec import DEFAULT_ROOT
from dev_lab.dev.venvpointer import shell_interpreter

_HOSTS = ('login01.example', 'login02.example')
_FLEET = (
    Grant(user='alice', hosts=_HOSTS, slurm_account='acct', cluster_name='c1'),
    Grant(user='bob', hosts=_HOSTS, slurm_account='acct', cluster_name='c1'),
    Grant(user='carol', hosts=_HOSTS, slurm_account='acct', cluster_name='c1'),
)

#: What each account's layer ``hosts/c1-<user>.toml`` declares -- the one source of its [deploy].
_DEPLOY = {
    'alice': (
        '[deploy]\nhost = "login02.example"\nroot = "src"\nrepos = [\n  { name = "dev-lab" },\n]\n[[hpc.grant]]\n'
    ),
    'bob': '[deploy]\nhost = "login01.example"\nroot = "work"\n',
    'carol': '',
}

_URL = 'https://forge.example/team/config-source.git'
#: The command builders never read the clone; :func:`_source` writes one for the runs.
_SRC = ConfigSource(Path('unread'), _URL)


def _source(
    tmp_path: Path,
    users: tuple[str, ...] = ('alice', 'bob', 'carol'),
    files: tuple[str, ...] | None = None,
    deploy: dict[str, str] = _DEPLOY,
) -> ConfigSource:
    """A config-source clone whose family grants *users* on ``c1``, an account file (*deploy*) per *files*."""
    clone = tmp_path / 'config-source'
    (clone / 'hosts').mkdir(parents=True, exist_ok=True)
    grants = ''.join(f'[[hpc.grant]]\nuser = "{u}"\ncluster = "c1"\nslurm_account = "acct"\n' for u in users)
    (clone / 'family.toml').write_text(grants, encoding='utf-8')
    for user in users if files is None else files:
        (clone / 'hosts' / f'c1-{user}.toml').write_text(deploy.get(user, ''), encoding='utf-8')
    return ConfigSource(clone, _URL)


def _run(
    tmp_path: Path, accounts: tuple[str, ...] = (), deploy: dict[str, str] = _DEPLOY
) -> tuple[int, list[list[str]], list[str]]:
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        _FLEET,
        accounts,
        home=tmp_path,
        source=_source(tmp_path, deploy=deploy),
        dry_run=False,
        say=said.append,
        launch=lambda dest, command, _log: started.append([dest, command]),
    )
    return code, started, said


def test_each_account_deploys_on_its_own_declared_host(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path, ('alice', 'bob'))
    assert code == 0
    assert [argv[0] for argv in started] == ['alice@login02.example', 'bob@login01.example']
    assert 'cd ~/work/dev-lab' in started[1][-1], "bob's declared root"
    assert {p.name for p in tmp_path.rglob('*.log')} == {'alice.log', 'bob.log'}
    assert not any(': refused' in line for line in said)


def test_an_account_with_no_declared_host_is_refused_and_the_rest_deploy(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path)
    assert code == 2
    assert [argv[0] for argv in started] == ['alice@login02.example', 'bob@login01.example']
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
    argv = [deploy_command(_FLEET[0], Target('login02.example', 'src'), _SRC, division)]
    assert '--fleet-role research --role-table ' in argv[-1]
    assert '{"read_only": true, "serves": false}' in argv[-1]
    assert '--fleet-role' not in deploy_command(_FLEET[1], Target('login01.example', 'work'), _SRC, division)


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
        source=_source(tmp_path),
        dry_run=False,
        say=said.append,
        launch=lambda dest, command, _log: started.append([dest, command]),
        division=division,
    )
    assert code == 2
    assert [argv[0] for argv in started] == ['alice@login02.example']
    assert any(line.startswith('bob:') and "'gone'" in line for line in said)


def test_the_remote_runs_the_accounts_own_deploy() -> None:
    argv = [deploy_command(_FLEET[0], Target('login02.example', 'src'), _SRC)]
    assert f'cd ~/src/dev-lab && {shell_interpreter(".")} -m dev_lab.dev.hpcaccount deploy' in argv[-1]
    assert '--grant-table' in argv[-1], 'the declared slice is the one source of the grant the deploy writes'


def _two_grants(tmp_path: Path, role: str, accounts: tuple[str, ...]) -> tuple[int, list[str]]:
    said: list[str] = []
    twice = (
        Grant(user='alice', hosts=_HOSTS, slurm_account='free', role=role, cluster_name='c1'),
        Grant(user='alice', hosts=('other.example',), slurm_account='cost', role=role, cluster_name='c1'),
        *_FLEET[1:],
    )
    code = deploy_fleet(
        twice,
        accounts,
        home=tmp_path,
        source=_source(tmp_path),
        dry_run=True,
        say=said.append,
        launch=lambda _dest, _command, _log: None,
    )
    return code, said


def test_a_research_account_may_hold_several_grants(tmp_path: Path) -> None:
    """A research account never serves (no tick), so two allocations on it are two grants, not two deploy hosts."""
    _code, said = _two_grants(tmp_path, 'research', ())
    assert not any('hold more than one' in line for line in said)


def test_another_accounts_grants_never_refuse_the_selected_account(tmp_path: Path) -> None:
    """Deploying bob is not refused because alice -- not deployed -- serves under two grants."""
    code, said = _two_grants(tmp_path, 'verification', ('bob',))
    assert code == 0
    assert not any('hold more than one' in line for line in said)


def test_an_account_with_two_grants_is_refused_rather_than_one_silently_kept(tmp_path: Path) -> None:
    code, said = _two_grants(tmp_path, 'verification', ())
    assert code == 2  # the control: a SERVING account with two grants has two tick hosts
    assert any("['alice'] serve under more than one [[hpc.grant]]" in line and '--account' in line for line in said)


def test_a_declared_short_host_resolves_to_its_grant_login_host(tmp_path: Path) -> None:
    """A machine file's ``login01`` IS the grant's ``login01.example``: the full name is what is dialled."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login01"\n'})
    assert code == 0
    assert [argv[0] for argv in started] == ['bob@login01.example']
    assert not any(': refused' in line for line in said)


def test_a_short_host_matching_no_grant_label_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a bare label that is no grant host's first label is still refused."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login"\n'})
    assert code == 2
    assert started == []
    assert any('not a login host' in line for line in said)


def test_a_short_host_two_grant_hosts_share_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a label naming two login hosts names neither, so it is refused, never the first kept."""
    twins = (
        Grant(user='bob', hosts=('login01.a.example', 'login01.b.example'), slurm_account='acct', cluster_name='c1'),
    )
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        twins,
        ('bob',),
        home=tmp_path,
        source=_source(tmp_path, users=('bob',), deploy={'bob': '[deploy]\nhost = "login01"\n'}),
        dry_run=False,
        say=said.append,
        launch=lambda dest, command, _log: started.append([dest, command]),
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
    """User ruling 2026-11-06: the role is read from the layer [deploy]; PLANTED CONTROL: bob declares none."""
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
    grant = Grant(user='carol', hosts=_HOSTS, slurm_account='acct', cluster_name='c1')
    why = declared_target(grant, lambda _cmd, _stdin=None: '# /srv/u/machine/config.toml\n')
    assert why == 'carol: refused -- no [deploy] host in /srv/u/machine/config.toml; deploy it once by hand'


def test_the_remote_refreshes_the_accounts_kit_before_it_deploys() -> None:
    """A dead account cannot heal itself: its kit only moves on its own tick, which never runs.

    So the remote first runs the kit's OWN tick (the one step that refreshes the host checkout, under its lock),
    records the sha it reached, and only then deploys -- whatever that tick exits (a research kit refreshes, then
    refuses to serve). PLANTED CONTROL: the account's own declared root still names both steps.
    """
    command = deploy_command(_FLEET[0], Target('login02.example', 'src'), _SRC)
    refresh = command.index('-m dev_lab.dev.hpcaccount tick dev-lab')
    recorded = command.index('rev-parse HEAD')
    deployed = command.index('-m dev_lab.dev.hpcaccount deploy')
    assert refresh < recorded < deployed
    assert command.count('cd ~/src/dev-lab') == 5  # first install, tick, drift, render, deploy
    assert 'tick dev-lab ;' in command or 'tick dev-lab;' in command, 'a refused tick never stops the deploy'


def test_the_refresh_runs_in_the_grants_environment() -> None:
    """A grant's ``setup`` (a module load the cluster's git needs) wraps the refresh, as it wraps the cron tick."""
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', setup=('module load git-x',))
    command = deploy_command(grant, Target('login02.example', 'src'), _SRC)
    assert command.index('module load git-x') < command.index('tick dev-lab')
    assert 'module load git-x' not in deploy_command(_FLEET[0], Target('login02.example', 'src'), _SRC)


def _rendered(tmp_path: Path, source: ConfigSource, *, dry_run: bool = False) -> tuple[int, list[list[str]], list[str]]:
    started: list[list[str]] = []
    said: list[str] = []
    code = deploy_fleet(
        _FLEET[:2],
        ('alice', 'bob'),
        home=tmp_path,
        source=source,
        dry_run=dry_run,
        say=said.append,
        launch=lambda dest, command, _log: started.append([dest, command]),
    )
    return code, started, said


def test_the_account_renders_its_own_layer_between_the_kits_tick_and_the_deploy() -> None:
    """User ruling 2026-11-15: the render runs ON the account, for ITS host file, before it deploys."""
    command = deploy_command(_FLEET[0], Target('login02.example', 'src'), _SRC)
    tick = command.index('tick dev-lab')
    render = command.index('-m dev_lab.dev.devhost render --host c1-alice --write --from "$HOME/src/config-source"')
    assert tick < command.index('-m dev_lab.dev.devhost drift') < render < command.index('hpcaccount deploy')
    assert ') && cd ~/src/dev-lab' in command, 'a failed render stops the deploy'
    assert 'git clone -q https://forge.example/team/config-source.git' in command
    assert '--backups "$HOME/.cache/dev-lab/$(date -u +%y/%m/%d)/devhost"' in command
    assert 'c1-bob' not in command, 'PLANTED CONTROL: another account is never rendered here'


def test_an_account_with_no_stored_reader_credential_is_refused_naming_the_door() -> None:
    command = render_command(_FLEET[1], Target('login01.example', 'work'), _SRC)
    assert "grep -qs '@forge.example' ~/.git-credentials ||" in command
    assert 'python -m dev_lab.dev.hpcaccount credential bob@login01.example' in command
    assert 'exit 2' in command
    assert command.index('.git-credentials') < command.index('git clone'), 'refused before any fetch'


def test_the_grants_setup_wraps_the_render() -> None:
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', setup=('module load git-x',), cluster_name='c1')
    command = render_command(grant, Target('login02.example', 'src'), _SRC)
    assert command.index('module load git-x') < command.index('git clone')


def test_a_missing_account_file_is_refused_before_any_ssh(tmp_path: Path) -> None:
    """PLANTED CONTROL: alice, whose file is declared, still deploys."""
    code, started, said = _rendered(tmp_path, _source(tmp_path, files=('alice',)))
    assert code == 2
    assert [argv[0] for argv in started] == ['alice@login02.example']
    assert any(line.startswith('bob: refused') and 'hosts/c1-bob.toml' in line for line in said)


def test_a_family_with_no_grant_for_the_account_is_refused(tmp_path: Path) -> None:
    code, started, said = _rendered(tmp_path, _source(tmp_path, users=('alice',), files=('alice', 'bob')))
    assert code == 2
    assert [argv[0] for argv in started] == ['alice@login02.example']
    assert any(line.startswith('bob: refused') and 'declares no [[hpc.grant]]' in line for line in said)


def test_a_grant_naming_no_cluster_is_refused(tmp_path: Path) -> None:
    said: list[str] = []
    bare = (Grant(user='alice', hosts=_HOSTS, slurm_account='acct'),)
    code = deploy_fleet(bare, (), home=tmp_path, source=_source(tmp_path), dry_run=True, say=said.append,
                        launch=lambda *_: None)  # fmt: skip
    assert code == 2
    assert any('names no cluster' in line for line in said)


def test_a_dry_run_prints_the_render_and_starts_nothing(tmp_path: Path) -> None:
    code, started, said = _rendered(tmp_path, _source(tmp_path), dry_run=True)
    assert code == 0
    assert started == []
    assert any(line.startswith('alice') and 'would start' in line and 'render --host c1-alice' in line for line in said)


def test_a_layered_account_deploys_to_its_layers_host_whatever_its_remote_file_says(tmp_path: Path) -> None:
    """The layer is the one source of [deploy]: a stale remote host is never read, so it never refuses.

    deploy-fleet opens no read of the account before it starts (it takes no ``connect``) and dials the layer's host;
    the render inside the deploy then overwrites the stale remote file.
    """
    code, started, said = _run(tmp_path, ('alice',), {'alice': '[deploy]\nhost = "login02"\n'})
    assert code == 0
    assert [argv[0] for argv in started] == ['alice@login02.example']
    assert '-m dev_lab.dev.devhost render --host c1-alice --write' in started[0][1]
    assert not any(': refused' in line for line in said)


def test_an_unstated_root_is_the_clusters_and_a_contrary_one_is_refused() -> None:
    """2026-11-16: a layer with no root fell back to the default and was refused against the cluster's root."""
    rooted = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', cluster_name='c1', root='/work/c1/alice')
    target = declared_target(rooted, lambda _cmd, _stdin=None: '[deploy]\nhost = "login02"\n')
    assert not isinstance(target, str), target
    assert target.root == '/work/c1/alice'
    contrary = declared_target(rooted, lambda _cmd, _stdin=None: '[deploy]\nhost = "login02"\nroot = "src"\n')
    assert isinstance(contrary, str), 'PLANTED CONTROL: a stated root that contradicts the cluster is still refused'
    assert 'is not the root its cluster declares' in contrary


def test_the_remote_read_still_refuses_a_stale_host_for_the_doors_that_use_it() -> None:
    """PLANTED CONTROL: the remote read (credential, forget, storage) keeps its refusal of a stale host."""
    stale = '# /srv/u/machine/config.toml\n[deploy]\nhost = "retired01"\n'
    why = declared_target(_FLEET[0], lambda _cmd, _stdin=None: stale)
    assert isinstance(why, str)
    assert 'retired01 is not a login host' in why


def test_a_layer_with_no_deploy_host_is_refused_naming_the_layer(tmp_path: Path) -> None:
    """PLANTED CONTROL: the layer is checked as the remote file was; carol's layer declares no host."""
    code, started, said = _run(tmp_path, ('carol',))
    assert (code, started) == (2, [])
    assert any(line.startswith('carol: refused') and 'c1-carol.toml' in line for line in said)


def test_the_remote_deploy_refusal_names_the_deploy_fleet_door(tmp_path: Path) -> None:
    """A rendered [deploy] differing from flags names the door that re-renders it, never 'edit it there'."""
    config = tmp_path / 'config.toml'
    config.write_text(
        '[deploy]\nhost = "login01.example"\n'
        'repos = [{ name = "dev-lab", url = "https://x.example/d.git", ref = "m" }]\n',
        encoding='utf-8',
    )
    argv = ['--host', 'login02.example', '--repo', 'dev-lab=https://x.example/d.git@m']
    why = account_deploy._declared(account_deploy._parser().parse_args(argv), config)
    assert isinstance(why, str)
    assert 'deploy-fleet --account' in why
    assert 'edit it there' not in why


_REPOS = (('dev-lab', 'https://forge.example/team/dev-lab.git', 'main'),)


def test_a_first_install_precedes_the_kits_tick_and_clones_the_layers_repos() -> None:
    command = deploy_command(_FLEET[0], Target('login02.example', 'src', repos=_REPOS), _SRC)
    assert command.index('[first-install]') < command.index('tick dev-lab')
    assert f'[ -x {shell_interpreter("~/src/dev-lab")} ] ||' in command
    assert 'git clone -q --branch main https://forge.example/team/dev-lab.git ~/src/dev-lab' in command
    assert '( cd ~/src/dev-lab && uv sync --frozen )' in command
    assert 'https://astral.sh/uv/install.sh' in command


def _first_install(tmp_path: Path, *, venv: bool) -> str:
    """Run the first-install line in bash against a fake home, ``uv``/``git``/``curl`` stubbed to record calls."""
    bash = shutil.which('bash')
    if bash is None:
        pytest.skip('no bash to run the remote line')
    home, stubs = tmp_path / 'home', tmp_path / 'stubs'
    (home / 'src' / 'dev-lab' / '.venv' / 'bin').mkdir(parents=True)
    stubs.mkdir()
    for tool in ('uv', 'git', 'curl'):
        (stubs / tool).write_text(f'#!/bin/sh\necho {tool} "$@" >> "$HOME/calls"\n', encoding='utf-8', newline='\n')
        (stubs / tool).chmod(0o755)
    if venv:
        python = home / 'src' / 'dev-lab' / '.venv' / 'bin' / 'python'
        python.write_text('#!/bin/sh\n', encoding='utf-8', newline='\n')
        python.chmod(0o755)
    line = first_install(_FLEET[0], Target('login02.example', 'src', repos=_REPOS))
    unix = f'"$(cygpath -u {stubs.as_posix()!r} 2>/dev/null || echo {stubs.as_posix()!r})"'
    script = f'export PATH={unix}:"$PATH"; {line}'
    subprocess.run([bash, '-c', script], env={**os.environ, 'HOME': home.as_posix()}, check=True, cwd=tmp_path)
    calls = home / 'calls'
    return calls.read_text(encoding='utf-8') if calls.is_file() else ''


def test_a_kit_with_no_venv_is_first_installed(tmp_path: Path) -> None:
    calls = _first_install(tmp_path, venv=False)
    assert 'uv sync --frozen' in calls
    assert 'curl' not in calls, 'a uv already on PATH is not reinstalled'


def test_a_kit_with_its_venv_skips_the_first_install(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same line, with the kit's interpreter present, runs nothing."""
    assert _first_install(tmp_path, venv=True) == ''
