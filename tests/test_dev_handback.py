"""``dev_lab.dev.handback``: a turn that hands the user a runnable command is refused at Stop."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import handback
from dev_lab.dev.handback import INTERACTIVE_ONLY, handed_commands, main, refusal


@pytest.fixture(autouse=True)
def _no_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about a handed command: the round gate (tests/test_dev_roundgate.py) reads no forge here."""
    monkeypatch.setattr(handback, 'round_refusal', lambda _cwd: None)


# The incident, 2026-10-26, verbatim in shape.
_INCIDENT = (
    "That failed only because your shell's current directory isn't the repo root. Here is the same command "
    'with an absolute path:\n\n`! /d/x/oa-r0/.venv/Scripts/python.exe -m dev_lab.dev.stoprun --pid 39240`'
)


@pytest.mark.parametrize(
    'text',
    [
        _INCIDENT,
        '! uv run app case run cases/case_a',
        'Please run:\n\n```bash\npython -m dev_lab.dev.verify tests\n```',
        'You can run `git push origin lane/x` to publish it.',
        '\u8bf7\u5728\u7ec8\u7aef\u8fd0\u884c:\n```\npython -m dev_lab.dev.stoprun --pid 1\n```',
        '\u8bf7\u6267\u884c `python -m dev_lab.dev.forge queue`',
        'Run this:\n```powershell\nGet-Process python\n```',
    ],
)
def test_a_command_handed_to_the_user_is_found(text: str) -> None:
    assert handed_commands(text), text
    assert refusal(text) is not None


@pytest.mark.parametrize(
    'text',
    [
        'Done. Ran `python -m dev_lab.dev.verify tests` myself: 12 passed.',
        'The hook reads `stop_hook_active` and lets a second stop through.',
        'Nothing for you to run; branch pr/x at abc123.',
        '! gh auth login',
        'Please run `gcloud auth login` -- it opens a browser I cannot drive.',
    ],
)
def test_a_report_or_an_interactive_login_is_let_through(text: str) -> None:
    assert refusal(text) is None, handed_commands(text)


def test_one_runnable_command_beside_a_login_still_blocks() -> None:
    """EVERY handed command must be interactive-only: a login does not launder the rest."""
    assert refusal('! gh auth login\n! python -m dev_lab.dev.stoprun --pid 4') is not None


def test_the_refusal_routes_the_agent_to_its_tool_and_names_the_command() -> None:
    reason = refusal(_INCIDENT)
    assert reason is not None
    assert 'stoprun --pid 39240' in reason
    assert 'yourself' in reason
    assert 'remedy' in reason
    assert 'login' in reason


def test_the_allow_set_is_interactive_logins_only() -> None:
    """PLANTED control on the data: no python, git or uv verb may hide in the allow-set."""
    assert INTERACTIVE_ONLY
    assert not [v for v in INTERACTIVE_ONLY if v.split()[0] in {'python', 'git', 'uv', 'node', 'pytest'}]


def _transcript(tmp_path: Path, *texts: str) -> Path:
    path = tmp_path / 't.jsonl'
    rows = [{'type': 'user', 'message': {'role': 'user', 'content': 'go'}}]
    rows += [
        {'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': t}]}} for t in texts
    ]
    path.write_text('\n'.join(json.dumps(r) for r in rows) + '\n', encoding='utf-8')
    return path


def _run(payload: dict) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(stdin=io.StringIO(json.dumps(payload))) == 0
    return out.getvalue()


def test_the_stop_hook_reads_the_last_assistant_message_from_the_transcript(tmp_path: Path) -> None:
    path = _transcript(tmp_path, 'Ran it myself.', _INCIDENT)
    decision = json.loads(_run({'hook_event_name': 'Stop', 'transcript_path': str(path)}))
    assert decision['decision'] == 'block'
    assert 'stoprun' in decision['reason']


def test_only_the_final_message_is_judged(tmp_path: Path) -> None:
    path = _transcript(tmp_path, _INCIDENT, 'Ran the stop myself; pid 39240 is gone.')
    assert _run({'hook_event_name': 'Stop', 'transcript_path': str(path)}) == ''


def test_a_subagent_stop_reads_its_own_transcript_and_the_payload_message_wins(tmp_path: Path) -> None:
    clean = _transcript(tmp_path, 'all done')
    payload = {'hook_event_name': 'SubagentStop', 'agent_transcript_path': str(clean), 'transcript_path': 'nope'}
    assert _run(payload) == ''
    assert json.loads(_run({**payload, 'last_assistant_message': _INCIDENT}))['decision'] == 'block'


def test_a_repeated_stop_is_let_through_and_a_bad_payload_never_blocks(tmp_path: Path) -> None:
    path = _transcript(tmp_path, _INCIDENT)
    assert _run({'hook_event_name': 'Stop', 'transcript_path': str(path), 'stop_hook_active': True}) == ''
    assert _run({'hook_event_name': 'Stop', 'transcript_path': str(tmp_path / 'missing.jsonl')}) == ''
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert main(stdin=io.StringIO('not json')) == 0
    assert out.getvalue() == ''
