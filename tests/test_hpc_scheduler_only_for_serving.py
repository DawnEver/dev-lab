"""SCHEDULER-ONLY-FOR-SERVING: the scheduler (crontab) is reached only through a SERVING account's path.

User, 2026-11-20: "why would a research host need cron? clean it up and build a mechanism." A cron line exists only
to tick a verification account's queue. So:

* the deploy builds its phases from the role (:func:`~dev_lab.dev.hpcaccount.deploy.phases_of`): a role that does
  not serve has none of :data:`~dev_lab.dev.hpcaccount.deploy.SERVING_PHASES`;
* every place in ``hpcaccount`` that touches crontab is a NAMED serving door (:data:`_SCHEDULER_DOORS`), found by an
  AST scan with a floor, so a new crontab call outside them reds here.

PLANTED CONTROLS: a research phase list carrying ``cron`` is refused by the same check, and a planted function that
calls ``crontab`` outside the doors is found by the same scan.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from dev_lab.dev.hpcaccount import deploy

_PACKAGE: Final = Path(deploy.__file__).parent
#: Every function allowed to touch the scheduler, and why it is a serving door.
_SCHEDULER_DOORS: Final = {
    ('deploy.py', '_cron'): 'the serving deploy phase (only phases_of(serves=True) holds it)',
    ('deploy.py', 'deploy'): '`deploy --remove`: the explicit door dropping our marked lines',
    ('cipause.py', 'ci_pause'): 'ci-pause of a serving account (refused unless the machine file serves)',
    ('cipause.py', 'ci_resume'): 'ci-resume of a serving account',
    ('drift.py', 'account_drift'): 'reads crontab only behind its VERIFICATION gate',
    ('steps.py', 'crontab'): 'the one writer every door above calls',
}
_TOUCHES: Final = ('crontab', 'cron_lines')


def _serving_only(phases: tuple[str, ...], *, serves: bool) -> list[str]:
    """The serving phases a role that does not serve would run; ``[]`` when it may."""
    return [] if serves else sorted(set(phases) & deploy.SERVING_PHASES)


def _callers(source: str, name: str) -> set[tuple[str, str]]:
    """``(file, function)`` of every call or attribute naming a scheduler touch in *source*."""
    found: set[tuple[str, str]] = set()
    for function in ast.walk(ast.parse(source)):
        if not isinstance(function, ast.FunctionDef):
            continue
        for node in ast.walk(function):
            called = node.func if isinstance(node, ast.Call) else node
            word = (
                called.id if isinstance(called, ast.Name) else called.attr if isinstance(called, ast.Attribute) else ''
            )
            if word in _TOUCHES:
                found.add((name, function.name))
    return found


def _scan(root: Path) -> set[tuple[str, str]]:
    return {hit for path in sorted(root.glob('*.py')) for hit in _callers(path.read_text(encoding='utf-8'), path.name)}


def test_a_role_that_does_not_serve_has_no_scheduler_phase() -> None:
    research, verification = deploy.phases_of(serves=False), deploy.phases_of(serves=True)
    assert _serving_only(research, serves=False) == []
    assert set(verification) >= deploy.SERVING_PHASES
    assert [name for name in verification if name not in deploy.SERVING_PHASES] == list(research), 'order kept'
    planted = (*research, 'cron')
    assert _serving_only(planted, serves=False) == ['cron'], 'PLANTED CONTROL: a research list carrying cron reds'


def test_the_scheduler_is_touched_only_by_its_named_serving_doors() -> None:
    found = _scan(_PACKAGE)
    assert len(found) >= 4, f'FLOOR: the scan must find the known doors, found {sorted(found)}'
    strays = sorted(found - set(_SCHEDULER_DOORS))
    assert strays == [], f'a scheduler touch outside the serving doors: {strays} (SCHEDULER-ONLY-FOR-SERVING)'


def test_a_planted_crontab_call_outside_the_doors_is_found(tmp_path: Path) -> None:
    (tmp_path / 'research.py').write_text('def deploy_research(step):\n    crontab(step, [])\n', encoding='utf-8')
    assert _scan(tmp_path) == {('research.py', 'deploy_research')}


@pytest.mark.parametrize('door', sorted(_SCHEDULER_DOORS))
def test_each_named_door_still_exists(door: tuple[str, str]) -> None:
    """A door that no longer touches the scheduler is a stale allowance: remove it from the table."""
    file, function = door
    assert (file, function) in _scan(_PACKAGE) or file == 'steps.py', f'{door} no longer touches the scheduler'
