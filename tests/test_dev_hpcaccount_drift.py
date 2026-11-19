"""``hpcaccount drift`` / ``drift-fleet``: an account against the render of its config source, read only, no secret."""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from _hpcaccount_fakes import FLEET, HOST, fleet_source, home_of, tools_of

from dev_lab.dev import hpcaccount
from dev_lab.dev.hpcaccount import accountset, deploy, drift
from dev_lab.dev.hpcaccount.spec import MARK, cron_lines, load

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


def test_a_secret_value_is_never_printed_but_its_planted_neighbour_is(
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
    assert "dev_lab.dev.hpcaccount drift --from '~/repos/config' --host c1-alice" in started[0]
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
