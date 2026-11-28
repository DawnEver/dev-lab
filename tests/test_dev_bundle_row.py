"""ARCHIVE-IS-NO-STORE: `git bundle create` is REFUSED through the REAL engine; reading a bundle is not.

INCIDENT (#1118): an agent parked a checkout's unlanded work as
``git bundle create output/logs/<date>/salvage/x.bundle --branches --glob=refs/salvage`` and nothing refused it;
it reached MERGE-OR-DELETE only after the user stopped it. ``hpcaccount salvage`` builds its bundle in Python,
not through a shell command, so this row does not reach it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks, walls
from dev_lab.dev.hook_adoption import HookAdoption, render

RULE = 'ARCHIVE-IS-NO-STORE'


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The registry rendered exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'git bundle create output/logs/26/11/28/salvage/x.bundle --branches --glob=refs/salvage',
        'git bundle create ../x.bundle origin/pr/a',
        'git bundle create --all x.bundle',
        'git bundle create -q x.bundle HEAD',
        'git -C ../lab bundle create out.bundle --all',
        'git -C "D:/a b/lab" bundle create out.bundle --all',
        'git -c core.quotepath=off bundle create x.bundle --all',
        'git --git-dir=../lab/.git bundle create x.bundle --all',
        'cd x && git bundle create y.bundle --all',
        'git fetch origin; git bundle create y.bundle --all',
        'git status && git bundle create y.bundle main 2>&1 | tail -1',
        '(cd x && git bundle create y.bundle --all)',
    ],
)
def test_a_bundle_create_is_refused_with_the_merge_or_delete_door(rules: Path, command: str) -> None:
    """Every shape is refused by the row, and the refusal names its door on its own line (walls.has_remedy)."""
    reason = agenthooks.decide(command, rules)
    assert reason is not None, f'not refused: {command!r}'
    assert reason.startswith(f'{RULE}:'), reason
    assert walls.has_remedy(reason), reason
    assert 'MERGE-OR-DELETE' in reason
    assert 'branchprune discard <branch> --approved' in reason


@pytest.mark.parametrize(
    'command',
    [
        'git bundle verify x.bundle',
        'git bundle list-heads x.bundle',
        'git bundle unbundle x.bundle',
        'git -C ../lab bundle verify out.bundle',
        'git commit -m "bundle create notes"',
        'git log --grep "bundle create"',
    ],
)
def test_reading_a_bundle_is_permitted(rules: Path, command: str) -> None:
    """PLANTED CONTROL: the read-only verbs pass, so the row is not a constant `git bundle` ban."""
    assert agenthooks.decide(command, rules) is None, command
