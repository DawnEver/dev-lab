r"""RECURSIVE-DELETE: a raw recursive delete is REFUSED through the REAL engine, and its near-misses are not.

INCIDENT 2026-10-27: an agent hand-built a delete list from ``git worktree list`` and ran
``Remove-Item -LiteralPath "\\\\?\\<path>" -Recurse -Force`` over it; one entry was a MAIN checkout,
deleted with its ``.git``, unpushed work and ``output/``, past the recycle bin. The door that decides
deletability (``branchset --apply`` -> ``reclaim``, which refuses a main checkout) existed and was
bypassed because no row refused the raw verb. Both shells are judged: the engine reads Bash and PowerShell.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import agenthooks, disclosure
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, rules_by_id


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The registry rendered exactly as a repo ships it."""
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'rm -rf .claude/worktrees/lane',
        'rm -fr ../motronics-studio',
        'rm -r src',
        'rm -R build',
        'rm --recursive --force C:/work/repo',
        'rm -v -r -f "C:/work/my repo"',
        'cd .. && rm -rf motronics-studio',
        'Remove-Item -LiteralPath "\\\\?\\C:\\work\\motronics-studio" -Recurse -Force',
        'Remove-Item C:\\work\\repo -Recurse',
        'remove-item -recurse -force C:\\work\\repo',
        'Remove-Item -Path C:\\work\\repo -r',
        'Remove-Item -Rec -Force $tree',
        'rm -Recurse -Force C:\\work\\repo',
        'rmdir /s /q C:\\work\\repo',
        'rd /S C:\\work\\repo',
        'cmd /c rmdir /s /q C:\\work\\repo',
        'cmd.exe /c "rd /s /q C:\\work\\repo"',
        'git worktree remove .claude/worktrees/lane',
        'git worktree remove --force C:/work/motronics-studio',
        'git -C C:/work/repo worktree remove --force x',
        'git clean -fdx',
        'git clean -fd',
        'git clean -x -f',
        'python -c "import shutil; shutil.rmtree(\'C:/work/repo\')"',
        'python -c "import shutil;shutil.rmtree(r\'C:\\work\\repo\', ignore_errors=True)"',
        'rm -rf /tmp/../home/me/repo',
    ],
)
@pytest.mark.workstation
def test_a_recursive_delete_is_refused_with_its_doors(rules: Path, command: str) -> None:
    """REFUSAL-NAMES-THE-REMEDY: the branchset door, and asking the user for anything else."""
    reason = agenthooks.decide(command, rules)
    assert reason is not None, f'not refused: {command!r}'
    assert 'RECURSIVE-DELETE' in reason, reason
    assert 'dev_lab.dev.branchset --apply' in reason
    assert 'ask the user' in reason


@pytest.mark.parametrize(
    'command',
    [
        'rm -rf /tmp/probe',
        'rm -rf "$TEMP/probe"',
        'rm -rf $TMPDIR/probe-1',
        'rmdir /s /q %TEMP%\\probe',
        'Remove-Item -Recurse -Force $env:TEMP\\probe',
        'Remove-Item -LiteralPath "C:\\Users\\me\\AppData\\Local\\Temp\\probe" -Recurse -Force',
        'rm -rf output/logs/26/10/27',
        'Remove-Item -Recurse output\\cache',
        'rm -rf C:/work/repo/output/logs/26',
        'rm notes.txt',
        'rm -f build.log',
        'Remove-Item -Force file.txt',
        'rmdir empty-dir',
        'rd empty-dir',
        'git worktree list --porcelain',
        'git clean -n',
        'git clean -f',
        'git commit -m "refuse rm -rf and Remove-Item -Recurse"',
        'grep -n "shutil.rmtree" src/a.py',
    ],
)
@pytest.mark.workstation
def test_a_scratch_target_or_a_non_recursive_delete_is_permitted(rules: Path, command: str) -> None:
    """System temp and `output/` are regenerable scratch; a single file or an empty dir is not a tree."""
    reason = agenthooks.decide(command, rules)
    assert reason is None or 'RECURSIVE-DELETE' not in reason, f'{command!r}: {reason}'


def test_the_refusal_is_progressive_and_universal() -> None:
    """INJECTED-TEXT-IS-PROGRESSIVE, and it needs nothing from a repo: it ships everywhere."""
    rule = rules_by_id(DENY_RULES)['RECURSIVE-DELETE']
    root = Path(__file__).resolve().parents[1]
    assert 'recursive-delete' in disclosure.anchors((root / disclosure.REFUSALS_DOC).read_text(encoding='utf-8'))
    assert rule.needs is None
    assert rule.rendered().get('severity', 'deny') != 'hint'
