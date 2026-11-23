"""TRACKED-CITES-NO-EPHEMERAL at the door: a rem journal append citing an ignored path is refused before it is written.

The incident (dev-lab#419): the commit-time check refused a journal line the append-only task guard then forbade
repairing. Each control below is planted in both directions -- the refused line, and its passing twin -- and is
driven through the REAL engine: the deny row prefilters there and asks ``journaldoor --admit`` only on a match, so
a shell call starts one interpreter, not two.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from dev_lab.dev import agent_wiring, agenthooks, ephemeralrefs, journaldoor, walls
from dev_lab.dev._deny_journal_row import REMEDY
from dev_lab.dev.hook_adoption import HookAdoption, render
from dev_lab.dev.hooks import DENY_RULES, rules_by_id

if os.name == 'nt':
    import _winapi

_TASK_JS = 'node "C:/x/rem/scripts/task.js"'
_ROW = rules_by_id(DENY_RULES)[ephemeralrefs.RULE]


@pytest.fixture(autouse=True)
def _no_project_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """The session's own CLAUDE_PROJECT_DIR would point the door at this checkout, not the planted repo."""
    monkeypatch.delenv('CLAUDE_PROJECT_DIR', raising=False)


def _repo(tmp_path: Path, *, venv: bool = True) -> Path:
    """A planted repo ignoring ``output/``, with the rendered rules installed and (by default) this venv to ask."""
    ephemeralrefs._door.run(['git', 'init', '-q'], cwd=tmp_path, check=True, timeout=60)
    (tmp_path / '.gitignore').write_text('/output/\n', encoding='utf-8')
    (tmp_path / 'doc.md').write_text('x\n', encoding='utf-8')
    ephemeralrefs._door.run(['git', 'add', '-A'], cwd=tmp_path, check=True, timeout=60)
    hooks = tmp_path / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    (hooks / 'deny-rules.json').write_text(render(HookAdoption(app_name='journal (suite)')), encoding='utf-8')
    if venv:
        target, link = Path(sys.executable).parents[1], tmp_path / '.venv'
        if os.name == 'nt':
            _winapi.CreateJunction(str(target), str(link))
        else:
            link.symlink_to(target, target_is_directory=True)
    return tmp_path


def _engine(root: Path, command: str, tool: str = 'Bash', *, logged: bool = False) -> str | None:
    """The real engine's refusal of *command* run in *root*, with *root*'s own rules; ``None`` when allowed."""
    rules = root / '.claude' / 'hooks' / 'deny-rules.json'
    return agenthooks.decide(command, rules, cwd=root, tool=tool, metrics_root=root if logged else None)


@pytest.mark.parametrize('verb', sorted(journaldoor.JOURNAL_VERBS))
@pytest.mark.parametrize('tool', ['Bash', 'PowerShell'])
def test_a_journal_verb_citing_an_ignored_path_is_denied_with_a_reachable_remedy(
    tmp_path: Path, verb: str, tool: str
) -> None:
    root = _repo(tmp_path)
    reason = _engine(root, f'{_TASK_JS} {verb} "swept output/logs/26/11/11/cleanup/" --task t', tool)
    assert reason is not None, f'{verb} citing an ignored path was let through'
    assert reason == (
        f"[{ephemeralrefs.RULE}] the task journal line cites ignored path 'output/logs/26/11/11/cleanup/'.\n"
        f'Remedy: {REMEDY}.'
    ), "the refusal text is the door's own, verbatim"
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
        f'{_TASK_JS} logs "output/x.log" --task t',  # PLANTED NEAR-MISS: a verb the prefix spells, not a verb
        f'cat > notes.md <<EOF\n{_TASK_JS} log "output/x.log"\nEOF',  # a sink's heredoc body is data
    ],
)
def test_the_passing_twin_is_allowed(tmp_path: Path, command: str) -> None:
    assert _engine(_repo(tmp_path), command) is None


def test_a_heredoc_an_interpreter_runs_is_still_judged(tmp_path: Path) -> None:
    """The sink twin's control: the same body EXECUTED by a shell appends, and is refused."""
    assert _engine(_repo(tmp_path), f'sh <<EOF\n{_TASK_JS} log "swept output/x.log" --task t\nEOF') is not None


def test_nobody_to_ask_admits_as_the_hook_did(tmp_path: Path) -> None:
    """No interpreter in the checkout: the engine asks nobody and admits; the commit-time check still stands."""
    assert _engine(_repo(tmp_path, venv=False), f'{_TASK_JS} log "swept output/x.log" --task t') is None


def test_the_appended_text_is_the_verbs_words_minus_its_flags() -> None:
    assert journaldoor.appended_texts(f'{_TASK_JS} decide --task t "use A" "over B" ; echo output/x') == [
        'use A over B'
    ]


def test_the_judge_answers_the_payload_by_exit_code(tmp_path: Path) -> None:
    """``--admit``: exit 1 with the refusal on stdout, else 0 and silent; a payload that is not a shell call is 0."""
    root = _repo(tmp_path, venv=False)

    def admit(command: str, tool: str = 'Bash') -> tuple[int, str]:
        payload = {'tool_name': tool, 'tool_input': {'command': command}, 'cwd': str(root)}
        out = io.BytesIO()
        code = journaldoor.main(['--admit'], stdin=io.BytesIO(json.dumps(payload).encode()), stdout=out)
        return code, out.getvalue().decode('utf-8')

    code, said = admit(f'{_TASK_JS} log "output/x.log" --task t')
    assert (code, said.startswith(f'[{ephemeralrefs.RULE}]')) == (1, True)
    assert admit(f'{_TASK_JS} log "see doc.md" --task t') == (0, '')
    assert admit(f'{_TASK_JS} log "output/x.log"', tool='Edit') == (0, '')


def test_the_door_is_an_engine_row_asking_the_judge_and_no_dispatcher_handler() -> None:
    """One interpreter per shell call: the row asks the judge; no WIRING row runs it as a handler."""
    assert _ROW.asks == journaldoor.__name__
    assert _ROW.severity == 'deny'
    assert not [w for w in agent_wiring.WIRING if w.module == journaldoor.__name__]


def test_a_denial_is_this_sessions_wall_through_the_one_choke_point(tmp_path: Path) -> None:
    """WALLS-ARE-RECORDED: the deny reaches the ledger with its rule and its remedy; a passing twin records none."""
    root = _repo(tmp_path)
    assert _engine(root, f'{_TASK_JS} log "see doc.md" --task t', logged=True) is None
    assert _engine(root, f'{_TASK_JS} log "swept output/logs/x.log" --task t', logged=True) is not None
    deadline, ledger = time.monotonic() + 60, walls.ledger(root)
    while not ledger.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    [line] = [json.loads(raw) for raw in ledger.read_text(encoding='utf-8').splitlines()]
    assert (line['rule'], line['remedy_present']) == (ephemeralrefs.RULE, True)
