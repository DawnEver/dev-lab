"""``hpcaccount deploy-fleet``: each declared account on ITS declared host, one detached ssh and one log each."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
from lab_commons.config import CONFIG_ENV
from lab_commons.home import HOME_ENV
from lab_commons.hpc.grants import Grant, Machine

from dev_lab.dev import devhost
from dev_lab.dev.hpcaccount import declaration
from dev_lab.dev.hpcaccount.division import Division, division_of
from dev_lab.dev.hpcaccount.fleet import (
    _READ_DEPLOY,
    ConfigSource,
    Target,
    declared_target,
    deploy_command,
    deploy_fleet,
    first_install,
    layer_target,
    render_command,
    repo_dir,
)
from dev_lab.dev.hpcaccount.fleetguard import stale_render
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
        '[deploy]\nhost = "login02.example"\nroot = "/r/src"\nrepos = [\n  { name = "dev-lab" },\n]\n[[hpc.grant]]\n'
    ),
    'bob': '[deploy]\nhost = "login01.example"\nroot = "/r/work"\n',
    'carol': '',
}

_URL = 'https://forge.example/team/config-source.git'
#: The command builders never read the clone; :func:`_source` writes one for the runs.
_SRC = ConfigSource(Path('unread'), _URL)


def _division(hpc: dict[str, Any]) -> Division:
    """The division of a machine reaching *hpc*'s grants, through the one reader (:func:`division_of`)."""
    grants = tuple(
        Grant(user=g['user'], hosts=('login01.example',), slurm_account='acct', qos='', role=g.get('role', ''))
        for g in hpc.get('grant', [])
    )
    return division_of(Machine(session=None, grants=grants, roles=hpc.get('roles') or {}))


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
    assert 'cd /r/work/repos/dev-lab' in started[1][-1], "bob's declared root"
    assert {p.name for p in tmp_path.rglob('*.log')} == {'alice.log', 'bob.log'}
    assert not any(': refused' in line for line in said)


def test_an_account_with_no_declared_host_is_refused_and_the_rest_deploy(tmp_path: Path) -> None:
    code, started, said = _run(tmp_path)
    assert code == 2
    assert [argv[0] for argv in started] == ['alice@login02.example', 'bob@login01.example']
    assert any(line.startswith('carol: refused') and '[deploy] host' in line for line in said)


def test_a_declared_host_outside_the_grant_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a machine file naming a host the grant does not is never ssh'd to."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "elsewhere.example"\nroot = "/r/src"\n'})
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
    division = _division({'grant': [{'user': 'alice', 'role': 'research'}, {'user': 'bob'}]})
    argv = [deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC, division)]
    assert '--fleet-role research --role-table ' in argv[-1]
    assert '{"read_only": true, "serves": false}' in argv[-1]
    assert '--fleet-role' not in deploy_command(_FLEET[1], Target('login01.example', '/r/work'), _SRC, division)


def test_a_grant_role_the_table_does_not_name_is_refused_before_any_ssh(tmp_path: Path) -> None:
    """PLANTED CONTROL: the account whose role the table names still deploys."""
    division = _division(
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
    argv = [deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)]
    assert f'cd /r/src/repos/dev-lab && {shell_interpreter(".")} -m dev_lab.dev.hpcaccount deploy' in argv[-1]
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
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login01"\nroot = "/r/src"\n'})
    assert code == 0
    assert [argv[0] for argv in started] == ['bob@login01.example']
    assert not any(': refused' in line for line in said)


def test_a_short_host_matching_no_grant_label_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: a bare label that is no grant host's first label is still refused."""
    code, started, said = _run(tmp_path, ('bob',), {'bob': '[deploy]\nhost = "login"\nroot = "/r/src"\n'})
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
        source=_source(tmp_path, users=('bob',), deploy={'bob': '[deploy]\nhost = "login01"\nroot = "/r/src"\n'}),
        dry_run=False,
        say=said.append,
        launch=lambda dest, command, _log: started.append([dest, command]),
    )
    assert code == 2
    assert started == []
    assert any('ambiguous' in line for line in said)


def test_the_kit_lives_in_the_declared_roots_repos_never_a_home_default() -> None:
    """User 2026-11-20: no CI-named home path; every account path derives from the declared root."""
    assert repo_dir(Target('login02.example', '/epccfs/p/u'), 'dev-lab').as_posix() == '/epccfs/p/u/repos/dev-lab'
    with pytest.raises(ValueError, match='root'):
        repo_dir(Target('login02.example', '.local/share/lab-forge/repos'), 'dev-lab')


def test_the_fleet_view_prints_each_accounts_declared_role(tmp_path: Path) -> None:
    """User ruling 2026-11-06: the role is read from the layer [deploy]; PLANTED CONTROL: bob declares none."""
    deploy = {**_DEPLOY, 'alice': '[deploy]\nhost = "login02.example"\nroot = "/r/src"\nrole = "research"\n'}
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
    command = deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)
    refresh = command.index('-m dev_lab.dev.hpcaccount tick dev-lab')
    recorded = command.index('rev-parse HEAD')
    deployed = command.index('-m dev_lab.dev.hpcaccount deploy')
    assert refresh < recorded < deployed
    assert command.count('cd /r/src/repos/dev-lab') == 5  # first install, tick, drift, render, deploy
    assert 'tick dev-lab ;' in command or 'tick dev-lab;' in command, 'a refused tick never stops the deploy'


def test_the_refresh_runs_in_the_grants_environment() -> None:
    """A grant's ``setup`` (a module load the cluster's git needs) wraps the refresh, as it wraps the cron tick."""
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', setup=('module load git-x',))
    command = deploy_command(grant, Target('login02.example', '/r/src'), _SRC)
    assert command.index('module load git-x') < command.index('tick dev-lab')
    assert 'module load git-x' not in deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)


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
    command = deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)
    tick = command.index('tick dev-lab')
    render = command.index('-m dev_lab.dev.devhost render --host c1-alice --write --from /r/src/repos/config-source')
    assert tick < command.index('-m dev_lab.dev.devhost drift') < render < command.index('hpcaccount deploy')
    assert ') && cd /r/src/repos/dev-lab' in command, 'a failed render stops the deploy'
    assert 'git clone -q https://forge.example/team/config-source.git' in command
    assert '--backups "$HOME/.cache/dev-lab/$(date -u +%y/%m/%d)/devhost"' in command
    assert 'c1-bob' not in command, 'PLANTED CONTROL: another account is never rendered here'


def test_an_account_with_no_stored_reader_credential_is_refused_naming_the_door() -> None:
    command = render_command(_FLEET[1], Target('login01.example', '/r/work'), _SRC)
    assert "grep -qs '@forge.example' ~/.git-credentials ||" in command
    assert 'python -m dev_lab.dev.hpcaccount credential bob@login01.example' in command
    assert 'exit 2' in command
    assert command.index('.git-credentials') < command.index('git clone'), 'refused before any fetch'


def test_a_declared_config_reader_reads_the_config_source_by_its_own_line() -> None:
    """A verification account holds forge-ci and the reader on one host: the url names the reader (2026-11-20).

    git's store answers a url carrying a user with THAT user's line only. PLANTED CONTROL: with no reader declared
    the url and the presence check stay login-free.
    """
    command = render_command(_FLEET[1], Target('login01.example', '/r/work'), _SRC, reader='server-reader')
    assert 'git clone -q https://server-reader@forge.example/team/config-source.git' in command
    assert 'remote set-url origin https://server-reader@forge.example/team/config-source.git' in command
    assert "grep -qs '://server-reader:[^@/]*@forge.example' ~/.git-credentials ||" in command
    assert '--login server-reader' in command
    plain = render_command(_FLEET[1], Target('login01.example', '/r/work'), _SRC)
    assert 'server-reader' not in plain
    assert 'git clone -q https://forge.example/team/config-source.git' in plain


def test_the_grants_setup_wraps_the_render() -> None:
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', setup=('module load git-x',), cluster_name='c1')
    command = render_command(grant, Target('login02.example', '/r/src'), _SRC)
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
    code, started, said = _run(tmp_path, ('alice',), {'alice': '[deploy]\nhost = "login02"\nroot = "/r/src"\n'})
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
    contrary = declared_target(rooted, lambda _cmd, _stdin=None: '[deploy]\nhost = "login02"\nroot = "/r/src"\n')
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
        '[deploy]\nhost = "login01.example"\nroot = "/r"\n'
        'repos = [{ name = "dev-lab", url = "https://x.example/d.git", ref = "m" }]\n',
        encoding='utf-8',
    )
    argv = ['--host', 'login02.example', '--repo', 'dev-lab=https://x.example/d.git@m']
    why = declaration.declaration(declaration.parser().parse_args(argv), config)
    assert isinstance(why, str)
    assert 'deploy-fleet --account' in why
    assert 'edit it there' not in why


_REPOS = (('dev-lab', 'https://forge.example/team/dev-lab.git', 'main'),)


def test_a_first_install_precedes_the_kits_tick_and_clones_the_layers_repos() -> None:
    command = deploy_command(_FLEET[0], Target('login02.example', '/r/src', repos=_REPOS), _SRC)
    assert command.index('[first-install]') < command.index('+refs/heads/main:refs/remotes/origin/main')
    assert f'[ -x {shell_interpreter("/r/src/repos/dev-lab")} ] ||' in command
    assert 'git clone -q --branch main https://forge.example/team/dev-lab.git /r/src/repos/dev-lab' in command
    assert '( cd /r/src/repos/dev-lab && uv sync --frozen )' in command
    assert 'https://astral.sh/uv/install.sh' in command


def _first_install(tmp_path: Path, *, venv: bool) -> str:
    """Run the first-install line in bash against a fake home, ``uv``/``git``/``curl`` stubbed to record calls."""
    bash = shutil.which('bash')
    assert bash, 'the first-install line runs in bash on the account'
    home, stubs, root = tmp_path / 'home', tmp_path / 'stubs', tmp_path / 'root'
    (root / 'repos' / 'dev-lab' / '.venv' / 'bin').mkdir(parents=True)
    home.mkdir()
    stubs.mkdir()
    for tool in ('uv', 'git', 'curl'):
        (stubs / tool).write_text(f'#!/bin/sh\necho {tool} "$@" >> "$HOME/calls"\n', encoding='utf-8', newline='\n')
        (stubs / tool).chmod(0o755)
    if venv:
        python = root / 'repos' / 'dev-lab' / '.venv' / 'bin' / 'python'
        python.write_text('#!/bin/sh\n', encoding='utf-8', newline='\n')
        python.chmod(0o755)
    line = first_install(_FLEET[0], Target('login02.example', root.as_posix(), repos=_REPOS))
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


_KIT_ROWS = (
    ('dev-lab', 'https://forge.example/team/dev-lab.git', 'integrate/main'),
    ('product', 'https://gitea.example/team/product.git', 'integrate/main'),
)


def test_a_declared_kit_ref_moves_the_kit_itself_never_through_the_stale_machine_file() -> None:
    """The kit fast-forwards to its LAYER-declared ref, under the cron tick's lock, before the render.

    Measured 2026-11-20: the kit's tick reads the account's OLD machine file -- one with a retired key crashed before
    refreshing, one with an old root refreshed ANOTHER checkout -- so the render then ran a kit too old for
    ``--from``. PLANTED CONTROL: a layer naming no kit row keeps the tick.
    """
    command = deploy_command(_FLEET[0], Target('login02.example', '/r/src', repos=_KIT_ROWS), _SRC)
    moved = command.index('+refs/heads/integrate/main:refs/remotes/origin/integrate/main')
    checkout = command.index('checkout -q -B integrate/main', moved)
    synced = command.index('uv sync --frozen', checkout)
    assert 'flock -w 600' in command
    assert '/serve/dev-lab.lock' in command
    assert synced < command.index('-m dev_lab.dev.devhost render')
    assert 'hpcaccount tick dev-lab' not in command
    unnamed = deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)
    assert 'hpcaccount tick dev-lab' in unnamed


def test_an_absolute_root_is_never_put_under_home() -> None:
    """Measured 2026-11-20 (Cirrus): root ``/epccfs/...`` rendered from ``$HOME//epccfs/...``, a path that is not."""
    command = render_command(_FLEET[0], Target('login02.example', '/abs/root'), _SRC)
    assert '--from /abs/root/repos/config-source' in command
    assert '$HOME' not in command.split('--from', 1)[1].split()[0], 'the clone is under the declared root'
    with pytest.raises(ValueError, match='root'):
        render_command(_FLEET[0], Target('login02.example', 'src'), _SRC)  # PLANTED CONTROL: no home-relative root


def test_a_first_install_clones_only_the_kit() -> None:
    """The kit alone is first installed; the deploy's ticks clone the rest.

    Measured 2026-11-20: a first install cloning a forge-hosted product repo before any reader credential failed, and
    the kit never got its venv.
    """
    command = first_install(_FLEET[0], Target('login02.example', '/r/src', repos=_KIT_ROWS))
    assert 'git clone -q --branch integrate/main https://forge.example/team/dev-lab.git /r/src/repos/dev-lab' in command
    assert 'product' not in command


def test_a_layer_naming_no_role_takes_its_grants_role(tmp_path: Path) -> None:
    """An account file no longer states a role (the family grant does); the grant's role is the target's.

    Measured 2026-11-20: ci-pause-fleet read every verification account as 'role undeclared' and skipped it.
    PLANTED CONTROL: a stated role is kept.
    """
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', cluster_name='c1', role='verification')
    plain = '[deploy]' + chr(10) + 'host = "login02.example"' + chr(10) + 'root = "/r/src"' + chr(10)
    bare = layer_target(grant, _source(tmp_path, users=('alice',), deploy={'alice': plain}))
    assert isinstance(bare, Target)
    assert bare.role == 'verification'
    stated = plain + 'role = "x"' + chr(10)
    kept = layer_target(grant, _source(tmp_path, users=('alice',), deploy={'alice': stated}))
    assert isinstance(kept, Target)
    assert kept.role == 'x'


def _workstation(tmp_path: Path, family: str) -> Path:
    clone = tmp_path / 'source'
    (clone / 'hosts').mkdir(parents=True)
    (clone / 'family.toml').write_text(family, encoding='utf-8')
    (clone / 'hosts' / 'WS.toml').write_text('[dev]\nhpc = ["research"]\n', encoding='utf-8')
    return clone


def test_deploy_fleet_refuses_a_machine_file_that_is_not_its_render(tmp_path: Path) -> None:
    """The deploy line is built from THIS machine's grants, so a stale render deploys stale family facts.

    Measured 2026-11-20: hosts-config gained a cluster `setup` (CC=gcc), but the workstation's machine file was never
    re-rendered, so every Cirrus deploy ran without it. Since a render restates no family leaf (#865), a family fact
    is read live under the machine file; what can go stale is the HOST layer, so the planted change is there.
    PLANTED CONTROL: the fresh render deploys.
    """
    clone = _workstation(tmp_path, '[hpc.clusters.c1]\nhosts = ["login01"]\n')
    fresh = tomllib.loads(devhost.render(clone, 'WS', {}))
    assert stale_render(fresh) == ''
    (clone / 'hosts' / 'WS.toml').write_text('[dev]\nhpc = ["research", "verification"]\n', encoding='utf-8')
    why = stale_render(fresh)
    assert 'devhost render' in why
    assert 'not the render' in why or 'absent' in why


def test_the_deploy_itself_runs_in_the_grants_setup() -> None:
    """The venvs the deploy builds compile in the cluster's declared environment, as its ticks run.

    Measured 2026-11-20 (Cirrus): the cluster setup (CC=gcc, a GNU linker) wrapped the refresh and the render but
    not the deploy, so numerics-lab built with Cray's `cc` and rust-lld refused its plugin options.
    PLANTED CONTROL: a grant with no setup deploys unwrapped.
    """
    grant = Grant(user='alice', hosts=_HOSTS, slurm_account='acct', setup=('export CC=gcc',), cluster_name='c1')
    command = deploy_command(grant, Target('login02.example', '/r/src'), _SRC)
    tail = command[command.rindex('-m dev_lab.dev.devhost render') :]
    assert tail.index('export CC=gcc') < tail.index('-m dev_lab.dev.hpcaccount deploy')
    plain = deploy_command(_FLEET[0], Target('login02.example', '/r/src'), _SRC)
    assert 'export CC=gcc' not in plain


def test_every_account_leaves_its_dated_log_even_when_it_exits_early(tmp_path: Path) -> None:
    """Measured 2026-11-20: two accounts' deploy-fleet runs left no new log, so their failure was unreadable.

    A refused account and a launch that fails before the deploy runs each write their cause to the account's log.
    PLANTED CONTROL: a started account's log names what was started.
    """
    said: list[str] = []

    def launch(dest: str, _command: str, _log: object) -> None:
        if dest.startswith('bob@'):
            msg = 'the held session of bob is recorded but its holder does not answer'
            raise RuntimeError(msg)

    code = deploy_fleet(
        _FLEET, (), home=tmp_path, source=_source(tmp_path, deploy=_DEPLOY), dry_run=False, say=said.append,
        launch=launch,
    )  # fmt: skip
    assert code == 2
    logs = {p.stem: p.read_text(encoding='utf-8') for p in tmp_path.rglob('*.log')}
    assert set(logs) == {'alice', 'bob', 'carol'}
    assert 'holder does not answer' in logs['bob']
    assert 'refused' in logs['carol']
    assert 'started' in logs['alice']
