"""REPORTS-LIVE-IN-MEMORY: an agent may not create Markdown under ``output/``, by Write/Edit or shell.

User ruling 2026-10-11. Planted controls on both halves: the same file under ``.claude/memory/`` is
admitted, and a program-written log (or a program writing its own ``.md`` through an argument rather
than an agent redirect) is unaffected.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from lab_commons.dev import agenthooks
from lab_commons.dev.codeplace import main
from lab_commons.dev.hook_adoption import HookAdoption, render
from lab_commons.dev.reportplace import refuse_report


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / '.git').mkdir()
    return tmp_path


@pytest.mark.parametrize(
    ('rel', 'refused'),
    [
        ('output/logs/26/10/10/audit/test-suite-audit.md', True),
        ('output/summary.md', True),
        ('output/REPORT.MD', True),
        ('.claude/worktrees/lane/output/x.md', True),
        ('.claude/memory/2026/10/10/test-suite-audit.md', False),
        ('docs-src/dev/page.md', False),
        ('output/logs/26/10/10/gate/measure.log', False),
        ('output/logs/26/10/10/case/table.csv', False),
        ('outputs/x.md', False),
    ],
)
def test_markdown_under_output_is_refused_and_memory_is_admitted(checkout: Path, rel: str, refused: bool) -> None:
    reason = refuse_report(checkout / rel)
    assert (reason is not None) is refused, rel
    if refused:
        assert 'REPORTS-LIVE-IN-MEMORY' in reason
        assert '.claude/memory/<yyyy>/<mm>/<dd>/' in reason
        assert 'MEMORY-SHAPE' in reason


def test_a_nested_worktree_is_judged_against_its_own_root(checkout: Path) -> None:
    lane = checkout / '.claude' / 'worktrees' / 'lane'
    (lane / '.git').mkdir(parents=True)
    assert 'output/x.md' in refuse_report(lane / 'output' / 'x.md')


def test_the_write_hook_denies_a_report_under_output_even_without_a_placement(checkout: Path, capsys) -> None:
    """The report half needs no `[tool.lab_commons.placement]`: the ruling is family-wide."""
    bad = json.dumps({'tool_name': 'Write', 'tool_input': {'file_path': str(checkout / 'output' / 'audit.md')}})
    assert main(stdin=io.StringIO(bad)) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision['permissionDecision'] == 'deny'
    assert 'REPORTS-LIVE-IN-MEMORY' in decision['permissionDecisionReason']
    good = json.dumps(
        {'tool_name': 'Edit', 'tool_input': {'file_path': str(checkout / '.claude/memory/2026/10/11/audit.md')}}
    )
    assert main(stdin=io.StringIO(good)) == 0
    assert capsys.readouterr().out == ''


@pytest.fixture(scope='module')
def rules(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp('rules') / 'deny-rules.json'
    path.write_text(render(HookAdoption(app_name='suite', remedies={})), encoding='utf-8')
    return path


@pytest.mark.parametrize(
    'command',
    [
        'echo x > output/logs/26/10/10/audit/test-suite-audit.md',
        'git log >> output/summary.md',
        'cat notes | tee output/logs/26/10/11/report/x.md',
        'cd sub && echo x > "output/findings.md"',
    ],
)
def test_a_shell_redirect_creating_a_report_under_output_is_refused(rules: Path, command: str) -> None:
    reason = agenthooks.decide(command, rules)
    assert reason is not None, command
    assert 'REPORTS-LIVE-IN-MEMORY' in reason
    assert '.claude/memory/' in reason


@pytest.mark.parametrize(
    'command',
    [
        'echo x > .claude/memory/2026/10/11/audit.md',
        'git log > output/logs/26/10/11/merge/log.txt',
        'cat output/logs/26/10/10/audit/test-suite-audit.md',
        'python -m pkg.run --out output/logs/26/10/11/case/comparison.md',
    ],
)
def test_memory_reads_and_program_written_output_are_unaffected(rules: Path, command: str) -> None:
    reason = agenthooks.decide(command, rules)
    assert reason is None or 'REPORTS-LIVE-IN-MEMORY' not in reason, (command, reason)
