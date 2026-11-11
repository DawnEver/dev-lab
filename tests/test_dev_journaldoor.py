"""TRACKED-CITES-NO-EPHEMERAL at the door: a rem journal append citing an ignored path is refused before it is written.

The incident (dev-lab#419): the commit-time check refused a journal line the append-only task guard then forbade
repairing. Each control below is planted in both directions -- the refused line, and its passing twin.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import agent_wiring, ephemeralrefs, journaldoor

_TASK_JS = 'node "C:/x/rem/scripts/task.js"'


@pytest.fixture(autouse=True)
def _no_project_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session's own CLAUDE_PROJECT_DIR would point the door at this checkout, not the planted repo."""
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)


def _repo(tmp_path: Path) -> Path:
    ephemeralrefs._door.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=60)
    (tmp_path / '.gitignore').write_text('/output/\n', encoding='utf-8')
    (tmp_path / 'doc.md').write_text('x\n', encoding='utf-8')
    ephemeralrefs._door.run(['git', 'add', '-A'], cwd=tmp_path, check=True, timeout=60)
    return tmp_path


def _hook(root: Path, command: str, tool: str = 'Bash') -> dict[str, object] | None:
    payload = {'tool_name': tool, 'tool_input': {'command': command}, 'cwd': str(root)}
    out = io.StringIO()
    assert journaldoor.main(stdin=io.StringIO(json.dumps(payload)), stdout=out) == 0
    return json.loads(out.getvalue()) if out.getvalue().strip() else None


@pytest.mark.parametrize('verb', sorted(journaldoor.JOURNAL_VERBS))
@pytest.mark.parametrize('tool', ['Bash', 'PowerShell'])
def test_a_journal_verb_citing_an_ignored_path_is_denied_with_a_reachable_remedy(
    tmp_path: Path, verb: str, tool: str
) -> None:
    root = _repo(tmp_path)
    decision = _hook(root, f'{_TASK_JS} {verb} "swept output/logs/26/11/11/cleanup/" --task t', tool)
    assert decision is not None, f'{verb} citing an ignored path was let through'
    out = decision['hookSpecificOutput']
    assert isinstance(out, dict)
    assert out['permissionDecision'] == 'deny'
    reason = str(out['permissionDecisionReason'])
    assert 'output/logs/26/11/11/cleanup/' in reason
    assert '<placeholder>' in reason, 'the remedy must name the rephrase the other guards allow'
    assert '`!' not in reason, 'the remedy never hands the user a command (AGENT-RUNS-ITS-OWN-COMMANDS)'


@pytest.mark.parametrize(
    'command',
    [
        f'{_TASK_JS} log "swept output/logs/<yy>/<mm>/<dd>/cleanup/" --task t',  # a shape, not content
        f'{_TASK_JS} log "see doc.md and memory the-sweep-ran" --task t',  # tracked, and a memory name
        f'{_TASK_JS} list && cat output/logs/x.log',  # not a journal verb; the chained read is not the text
        f'{_TASK_JS} log "done" --task t && cat output/logs/x.log',  # the cite is outside the appended text
        'git commit -m "swept output/logs/x.log"',  # not the journal door at all
    ],
)
def test_the_passing_twin_is_allowed(tmp_path: Path, command: str) -> None:
    assert _hook(_repo(tmp_path), command) is None


def test_the_appended_text_is_the_verbs_words_minus_its_flags() -> None:
    assert journaldoor.appended_texts(f'{_TASK_JS} decide --task t "use A" "over B" ; echo output/x') == [
        'use A over B'
    ]


def test_a_payload_that_is_not_a_shell_call_is_silent(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    assert _hook(root, f'{_TASK_JS} log "output/x.log"', tool='Edit') is None


def test_the_commit_time_refusal_names_the_door_and_a_human_remedy_for_a_journal() -> None:
    remedy = ephemeralrefs.remedy_for([".claude/tasks/t/JOURNAL.md:3: cites ignored path 'output/x'"])
    assert journaldoor.__name__ in remedy, 'the commit-time refusal names the door-time one'
    assert 'editor' in remedy, 'an append-only journal line is repaired by the user in an editor'
    assert ephemeralrefs.remedy_for(["doc.md:1: cites ignored path 'output/x'"]) == ephemeralrefs.REMEDY


def test_the_door_is_wired_before_every_shell_call() -> None:
    wired = [w for w in agent_wiring.WIRING if w.marker == journaldoor.__name__]
    assert [(w.event, w.on_shells) for w in wired] == [('PreToolUse', True)]
    assert f'-m {journaldoor.__name__}' in wired[0].command
