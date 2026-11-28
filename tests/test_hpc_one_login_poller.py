"""ONE-LOGIN-POLLER: an HPC login node runs exactly ONE cron poller per account (user ruling 2026-11-27).

The account's crontab holds at most one line this tool marks -- one tick of every served repo under one lock
(:func:`~dev_lab.dev.hpcaccount.cronline.cron_lines`) -- and no unmarked family line (a hand-written or stale poller).
Every door that writes or reads it says so: ``deploy`` and ``ci-resume`` (through
:func:`~dev_lab.dev.hpcaccount.steps.crontab`) refuse to write such a crontab and ``look crontab`` refuses it, each
naming every offending line (:func:`~dev_lab.dev.hpcaccount.cronline.crontab_refusal`).

PLANTED CONTROLS: a two-line marked crontab and an unmarked family poller are each refused by the same check that
passes the one marked line beside a user's own line.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest

from dev_lab.dev.hpcaccount import cronline, look
from dev_lab.dev.hpcaccount import spec as deploy_spec
from dev_lab.dev.hpcaccount.fleet import Target
from dev_lab.dev.hpcaccount.steps import Step, Tools, crontab

FORGE: Final = 'https://forge.example/team'
MINE: Final = '0 1 * * * echo mine'
ONE: Final = (
    f'3-59/15 * * * * cd /r/repos/dev-lab && python -m dev_lab.dev.hpcaccount tick dev-lab alpha {cronline.MARK}tick'
)
TWO: Final = f'7-59/15 * * * * cd /r/repos/dev-lab && python -m dev_lab.dev.hpcaccount tick beta {cronline.MARK}beta'
STRAY: Final = '*/5 * * * * cd /r/repos/dev-lab && .venv/bin/python -m dev_lab.dev.hpcaccount tick alpha'
FOREIGN: Final = '*/5 * * * * cd /r/lab-commons && .venv/bin/python -m lab_commons.hpc.poll'

FAKE_CRONTAB: Final = r"""
import pathlib, sys
state = pathlib.Path(sys.argv[1])
if sys.argv[2] == '-l':
    if not state.exists():
        sys.stderr.write('no crontab for me\n'); sys.exit(1)
    sys.stdout.write(state.read_text())
elif sys.argv[2] == '-':
    state.write_text(sys.stdin.read())
"""


def test_an_accounts_cron_lines_are_exactly_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE PIN: a serving account's declaration derives exactly one line, whatever its repo count."""
    repos = tuple(deploy_spec.Repo(name, f'{FORGE}/{name}.git', 'trunk') for name in (deploy_spec.KIT, 'a', 'b', 'c'))
    spec = deploy_spec.Deployment('h', '/r/src', '3.13', repos, role=deploy_spec.VERIFICATION)
    monkeypatch.setattr(deploy_spec, 'served', lambda _spec: frozenset({'a', 'b', 'c'}))
    lines = cronline.cron_lines(spec, tmp_path)
    assert len(lines) == 1, lines
    assert cronline.crontab_refusal('\n'.join([MINE, *lines])) == ''


def test_one_marked_line_beside_the_users_own_passes() -> None:
    assert cronline.crontab_refusal(f'{MINE}\n{ONE}\n') == ''
    assert cronline.crontab_refusal('') == ''


def test_planted_two_marked_lines_are_refused_naming_each() -> None:
    why = cronline.crontab_refusal(f'{MINE}\n{ONE}\n{TWO}\n')
    assert 'ONE-LOGIN-POLLER' in why
    assert ONE in why
    assert TWO in why
    assert MINE not in why


def test_planted_unmarked_family_poller_is_refused_naming_it() -> None:
    why = cronline.crontab_refusal(f'{ONE}\n{STRAY}\n')
    assert 'ONE-LOGIN-POLLER' in why
    assert STRAY in why
    assert cronline.crontab_refusal(f'# {STRAY}\n{ONE}\n') == '', 'a commented-out line runs nothing'


def _step(tmp_path: Path, text: str | None) -> tuple[Step, Path]:
    state = tmp_path / 'crontab.txt'
    if text is not None:
        state.write_text(text, encoding='utf-8')
    fake = tmp_path / 'crontab.py'
    fake.write_text(FAKE_CRONTAB, encoding='utf-8')
    return Step(Tools(crontab=(sys.executable, str(fake), str(state))), dry=False), state


def test_the_crontab_writer_refuses_a_foreign_family_line_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A family line no deploy wrote is its holder's: refused by name. PLANTED CONTROL: the user's own line is kept."""
    step, state = _step(tmp_path, f'{MINE}\n{FOREIGN}\n')
    assert crontab(step, [ONE]) == 2
    err = capsys.readouterr().err
    assert FOREIGN in err
    assert 'ONE-LOGIN-POLLER' in err
    assert state.read_text(encoding='utf-8') == f'{MINE}\n{FOREIGN}\n', 'nothing written'
    step, state = _step(tmp_path, f'{MINE}\n')
    assert crontab(step, [ONE]) == 0
    assert state.read_text(encoding='utf-8') == f'{MINE}\n{ONE}\n'


def test_planted_seven_marked_lines_become_exactly_the_one_tick(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Ezztz 2026-11-27: seven per-repo marked lines from an older deploy. The deploy REPLACES them, never refuses.

    An unmarked line running the deploy's own verb (``dev_lab.dev.hpcaccount``) is the deploy's too; the user's own
    line stays. Each removed line is printed.
    """
    old = [
        f'{n}-59/15 * * * * cd /r/dev-lab && python -m dev_lab.dev.hpcaccount tick r{n} {cronline.MARK}r{n}'
        for n in range(7)
    ]
    step, state = _step(tmp_path, '\n'.join([MINE, *old, STRAY]) + '\n')
    assert crontab(step, [ONE]) == 0
    assert state.read_text(encoding='utf-8') == f'{MINE}\n{ONE}\n'
    out = capsys.readouterr().out
    assert all(f'remove {line}' in out for line in [*old, STRAY]), out


def test_the_crontab_writer_refuses_two_lines(tmp_path: Path) -> None:
    step, state = _step(tmp_path, None)
    assert crontab(step, [ONE, TWO]) == 2
    assert not state.exists()


def test_look_crontab_refuses_a_crontab_with_two_pollers(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the same read of one marked line exits 0."""
    held = {'text': f'{MINE}\n{ONE}\n{TWO}\n'}
    grant = SimpleNamespace(user='u1')
    monkeypatch.setattr(look, 'reached_machine', lambda _users: SimpleNamespace(grants=[grant]))
    monkeypatch.setattr(look, 'declared_target', lambda _g, _shell: Target('login1', '/r'))

    def runner(_command: str, _stdin: str | None) -> str:
        return held['text']

    fleet = {'connect': lambda _g: runner, 'pin': lambda _g, _host: runner}
    said: list[str] = []
    assert look.look('u1', 'crontab', say=said.append, **fleet) == 2
    assert any('ONE-LOGIN-POLLER' in line and TWO in line for line in said), said
    held['text'] = f'{MINE}\n{ONE}\n'
    said.clear()
    assert look.look('u1', 'crontab', say=said.append, **fleet) == 0
