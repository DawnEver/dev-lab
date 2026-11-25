"""``hpcaccount drift`` / ``drift-fleet``: an account against the render of its config source, read only, no secret."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import FAMILY, FLEET, HOST, fleet_source, home_of, tools_of

from dev_lab.dev import devhost, hpcaccount
from dev_lab.dev.hpcaccount import accountset, deploy, drift
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load
from dev_lab.dev.hpcaccount.steps import Step
from dev_lab.dev.venvpointer import RETIRED_POINTER

TOKEN: Final = 'ghp_' + 'Zq9' * 14  # a long encoded value under an innocent key
HIDDEN: Final = 'hunter2-not-encoded'


@pytest.fixture(autouse=True)
def _slurm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deploy, 'slurm_dirs', lambda: ['/opt/slurm/bin'])


def _tree(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


def _run(tmp_path: Path, extra: str = '', mine: str = '') -> tuple[int, dict[str, bytes], dict[str, bytes]]:
    home, clone, machine = home_of(tmp_path, extra)
    spec = load(machine)
    lines = cron_lines(spec, home, slurm=['/opt/slurm/bin']) if spec else []
    (tmp_path / 'crontab.txt').write_text(mine + ''.join(f'{line}\n' for line in lines), encoding='utf-8')
    tools = tools_of(tmp_path)
    before = _tree(tmp_path)
    args = ['--from', str(clone), '--host', HOST, '--config', str(machine)]
    return drift.main(args, home=home, tools=tools), before, _tree(tmp_path)


def test_an_account_that_is_its_render_agrees(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, before, after = _run(tmp_path)
    assert code == 0, capsys.readouterr()
    assert 'agrees' in capsys.readouterr().out
    assert before == after


def test_drift_reports_three_lists_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    extra = '\n[user]\nshell = "zsh"\n'
    code, before, after = _run(tmp_path, extra, mine='0 1 * * * echo mine\n')
    out = capsys.readouterr().out
    assert code == 1
    assert 'machine file: only on the account' in out
    assert 'user.shell = "zsh"' in out
    assert 'crontab: only on the account' in out
    assert 'echo mine' in out
    assert before == after, 'drift wrote on the account'


def test_a_secret_value_is_never_printed_but_its_planted_neighbor_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    extra = f'\n[user]\nshell = "zsh"\nmirror = "{TOKEN}"\npassword = "{HIDDEN}"\n'
    code, _, _ = _run(tmp_path, extra, mine=f'0 2 * * * curl -H "x: {TOKEN}" x\n0 3 * * * API_KEY=abc run\n')
    out = capsys.readouterr().out
    assert code == 1
    assert TOKEN not in out
    assert HIDDEN not in out
    assert 'API_KEY=abc' not in out
    assert out.count('<redacted, sha256:') == 4
    assert '"zsh"' in out, 'the planted control: a plain value IS printed'


def test_compare_lines_names_a_differing_marked_line_once() -> None:
    found = drift.compare_lines([f'old tick {MARK}dev-lab', 'mine'], [f'new tick {MARK}dev-lab'])
    assert found.only_on_account == ('mine',)
    assert found.only_in_render == ()
    assert found.differing == (f'old tick {MARK}dev-lab (render: new tick {MARK}dev-lab)',)


def test_a_stale_clone_is_refused_not_crashed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    home, _, machine = home_of(tmp_path)
    args = ['--from', str(tmp_path / 'gone'), '--host', HOST, '--config', str(machine)]
    assert drift.main(args, home=home, tools=tools_of(tmp_path)) == 2
    assert 'deploy-fleet fetches that clone' in capsys.readouterr().err


def fleet(
    tmp_path: Path, accounts: tuple[str, ...], clusters: tuple[str, ...], *, verb: str = 'drift', ci: bool = False
) -> tuple[int, list[str], list[str]]:
    """Run a fleet verb over :data:`FLEET`; its code, the started ``dest command`` lines and what it said."""
    started: list[str] = []
    said: list[str] = []
    code = accountset.start_on_selected(
        FLEET, accounts, clusters, home=tmp_path, source=fleet_source(tmp_path), say=said.append, verb=verb,
        serving_only=(lambda target: target.role == 'verification') if ci else None,
        launch=lambda dest, command, _log: started.append(f'{dest} {command}'),
    )  # fmt: skip
    return code, started, said


def test_drift_fleet_runs_only_the_read_only_drift_from_the_fetched_clone(tmp_path: Path) -> None:
    code, started, _ = fleet(tmp_path, (), ('c1',))
    assert code == 0
    assert [line.split()[0] for line in started] == ['alice@login01.example', 'rita@login01.example']
    clone = (tmp_path / 'root' / 'repos' / 'config').as_posix()
    assert f'dev_lab.dev.hpcaccount drift --from {clone} --host c1-alice' in started[0], 'the clone is under the root'
    for word in ('render', 'pull', 'clone ', 'crontab -', '--write'):
        assert word not in started[0]


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


@pytest.mark.parametrize('verb', ['backup', 'backup-fleet'])
def test_the_retired_backup_verbs_are_no_verb(verb: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert hpcaccount.main([verb, '--account', 'alice']) == 2
    assert 'drift' in capsys.readouterr().err


@pytest.mark.parametrize('flags', [(), ('--dry-run',)])
def test_a_fleet_verb_with_no_forwarded_flag_parses(monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...]) -> None:
    """``drift-fleet`` declares no forwarded flag, so its parser never adds ``forwarded``: it must still parse.

    MEASURED 2026-11-17: ``drift-fleet --cluster c`` crashed with AttributeError before reaching a host. The tests
    above drive :func:`accountset.start_on_selected` directly and never parsed. PLANTED CONTROL: a verb that does
    declare a flag parses the same way.
    """

    def refuse(_accounts: object) -> None:
        raise LookupError

    monkeypatch.setattr(accountset, 'reached_machine', refuse)
    assert accountset.main_fleet(['--cluster', 'c1'], verb='drift', flags=flags) == 2


def test_old_copies_are_listed_with_their_files_and_never_touched(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pre-layout copies and a retired ``.venv-current`` are listed with the door that removes them; drift does not.

    PLANTED CONTROL: the declared layout's own ``repos/<repo>`` and ``envs`` are no old copy.
    """
    home, root = tmp_path / 'home', tmp_path / 'root'
    for old in (home / 'ci' / 'trees' / 'abc', home / '.local' / 'share' / 'lab-forge', root / 'src'):
        old.mkdir(parents=True)
    (root / 'repos' / 'r').mkdir(parents=True)
    (root / 'repos' / 'r' / '.venv-current').write_text('x', encoding='utf-8')
    (root / 'repos' / 'r' / '.venv').mkdir()  # PLANTED CONTROL: the pointer itself is no old copy
    (root / 'envs' / 'k').mkdir(parents=True)
    code, before, after = _run(tmp_path)
    out = capsys.readouterr().out
    assert code == 1
    assert f'old copies ({drift.REMOVED_BY}):' in out
    assert 'hpcaccount retention --account <user> [--apply]' in drift.REMOVED_BY
    assert '2026-11-22' in drift.REMOVED_BY
    assert f'  {(home / "ci").as_posix()}: 3 files' in out
    assert f'  {(home / ".local/share/lab-forge").as_posix()}: 1 files' in out
    assert f'  {(root / "src").as_posix()}: 1 files' in out
    assert f'  {(root / "repos/r/.venv-current").as_posix()}: 1 files' in out
    assert f'{(root / "repos/r/.venv").as_posix()}:' not in out
    assert 'envs' not in out
    assert f'{(root / "repos/r").as_posix()}:' not in out
    assert before == after, 'drift removed nothing'


def test_old_copies_never_block_a_pause() -> None:
    found = {drift.STRAYS: drift.Drift(only_on_account=('/h/ci: 3 files',)), 'crontab': drift.Drift()}
    assert drift.unrenderable(found) == [], 'an old copy is no config the account would lose'
    found['crontab'] = drift.Drift(only_on_account=('echo mine',))
    assert drift.unrenderable(found) == ['crontab: echo mine'], 'PLANTED CONTROL'


def test_discard_drift_rerenders_the_account_dropping_only_what_the_source_cannot_render(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``drift --discard-drift`` is the door for keys only the account holds.

    Measured 2026-11-20: alyyw103's ``capabilities.femm = {}`` had no door short of raw ssh. ``--dry-run`` lists and
    writes nothing; the real run re-renders the machine file from the config source with a backup, and drift then
    agrees. PLANTED CONTROL: plain drift still writes nothing.
    """
    extra = '\n[stray]\nfemm = {}\n'
    home, clone, machine = home_of(tmp_path, extra)
    spec = load(machine)
    lines = cron_lines(spec, home, slurm=['/opt/slurm/bin']) if spec else []
    (tmp_path / 'crontab.txt').write_text(''.join(f'{line}\n' for line in lines), encoding='utf-8')
    tools = tools_of(tmp_path)
    args = ['--from', str(clone), '--host', HOST, '--config', str(machine)]
    before = machine.read_bytes()
    assert drift.main(args, home=home, tools=tools) == 1
    assert machine.read_bytes() == before, 'the planted control: plain drift writes nothing'
    assert drift.main([*args, '--discard-drift', '--dry-run'], home=home, tools=tools) == 1
    assert 'would discard' in capsys.readouterr().out
    assert machine.read_bytes() == before
    assert drift.main([*args, '--discard-drift'], home=home, tools=tools) == 0
    out = capsys.readouterr().out
    assert 'discarded' in out
    assert 'stray' not in machine.read_text(encoding='utf-8')
    assert list((home / '.cache' / 'dev-lab').rglob('*')), 'the previous file is backed up'
    assert drift.main(args, home=home, tools=tools) == 0


def test_drift_fleet_forwards_discard_drift_and_dry_run() -> None:
    source = inspect.getsource(hpcaccount)
    assert "verb='drift', flags=('--dry-run', '--discard-drift')" in source


def test_a_research_account_reads_no_crontab_and_agrees(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SCHEDULER-ONLY-FOR-SERVING: a research account has no cron to compare, so drift never runs ``crontab``.

    Measured 2026-11-20 (Cirrus): a cluster forbidding crontab refused a research account's drift. PLANTED CONTROL:
    the verification account of the same fixture still reads crontab, and is refused when it cannot.
    """
    monkeypatch.setenv('FAKE_CRONTAB_FORBID', '1')
    (tmp_path / 'served').mkdir()
    (tmp_path / 'research').mkdir()
    code, _before, _after = _run(tmp_path / 'served')
    assert code == 2, 'the planted control: a serving account needs its crontab'
    capsys.readouterr()
    research = tmp_path / 'research'
    home, clone, machine = home_of(research, family=FAMILY.replace('"verification"', '"research"'))
    args = ['--from', str(clone), '--host', HOST, '--config', str(machine)]
    assert drift.main(args, home=home, tools=tools_of(research)) == 0, capsys.readouterr()
    assert 'agrees' in capsys.readouterr().out


def _rootless(tmp_path: Path, family: str) -> dict[str, drift.Drift] | str:
    """The drift of an account whose layer states no root, under *family*."""
    tmp_path.mkdir(exist_ok=True)
    home, clone, machine = home_of(tmp_path, family=family)
    layer = clone / devhost.host_file(HOST)
    held = layer.read_text(encoding='utf-8').splitlines(keepends=True)
    layer.write_text(''.join(line for line in held if not line.startswith('root = ')), encoding='utf-8')
    machine.write_text(devhost.render(clone, HOST, {}), encoding='utf-8')
    return drift.account_drift(Step(tools_of(tmp_path), dry=True), home, machine, clone, HOST)


def test_an_account_at_its_clusters_root_is_compared_at_that_root(tmp_path: Path) -> None:
    """A layer stating no root is the rule: the family's ``[hpc.clusters.<c>] root`` holds it, as the deploy reads it.

    Measured 2026-11-22: ``drift`` (and so ``ci-pause``) refused "no root declared" on every such account, though the
    deploy of the same account resolved the root from its grant. The root is the GRANT's cluster's: another
    cluster's root, declared first, is never taken. PLANTED CONTROL: with no root declared anywhere it still refuses.
    """
    mine, other = tmp_path / 'mine' / 'root', tmp_path / 'other'
    for root in (mine, other):
        (root / 'repos' / 'kit').mkdir(parents=True)
        (root / 'repos' / 'kit' / RETIRED_POINTER).write_text('x', encoding='utf-8')
    accounts = '[hpc.clusters.c0.slurm_accounts.a]\nbilled = false\n'
    elsewhere = f'[hpc.clusters.c0]\nhosts = ["login00"]\nroot = "{other.as_posix()}"\n{accounts}'
    own = FAMILY.replace('hosts = ["login01"]', f'hosts = ["login01"]\nroot = "{mine.as_posix()}"')
    head, clusters = own.split('[hpc.clusters.c1]', 1)
    found = _rootless(tmp_path / 'mine', f'{head}{elsewhere}[hpc.clusters.c1]{clusters}')
    assert not isinstance(found, str), found
    (stray,) = found[drift.STRAYS].only_on_account
    assert stray.startswith(mine.as_posix()), 'the old copies are read under the grant cluster root'
    refused = _rootless(tmp_path / 'bare', FAMILY)
    assert isinstance(refused, str)
    assert 'no root declared' in refused
