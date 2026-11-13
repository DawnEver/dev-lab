"""WALLS-ARE-RECORDED: every refusal is one ledger line, and a session does not end over a wall that taught nothing."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from dev_lab.dev import metrics, walls
from dev_lab.dev.datedlog import date_parts

SESSION = 'session-a'
REMEDIED = (
    'GIT-STASH: refused; a stash hides work from every scan.\nCommit on a lane instead.\n'
    'details: docs-src/dev/refusals.md#git-stash'
)


def _lines(root: Path) -> list[dict[str, object]]:
    return [json.loads(raw) for raw in walls.ledger(root).read_text(encoding='utf-8').splitlines()]


def _stop(root: Path, *, again: bool = False, session: str = SESSION) -> dict[str, object] | None:
    out = io.StringIO()
    payload = {'session_id': session, 'cwd': str(root), 'stop_hook_active': again}
    assert walls.main(['stop'], stdin=io.StringIO(json.dumps(payload)), out=out) == 0
    return json.loads(out.getvalue()) if out.getvalue() else None


def test_the_ledger_is_dated_program_output_under_the_checkout(tmp_path: Path) -> None:
    yy, mm, dd = date_parts()
    assert walls.ledger(tmp_path) == tmp_path / 'output' / 'logs' / yy / mm / dd / 'walls' / 'walls.jsonl'


def test_a_wall_line_carries_a_digest_never_the_command(tmp_path: Path) -> None:
    """The command may hold a secret, so only a sha256 prefix of it is written."""
    secret = 'curl -H "Authorization: token s3cr3t" https://forge.example/api'  # noqa: S105 -- the planted secret
    walls.record(tmp_path, rule='FORGE-WRITE-VIA-HTTP', command=secret, remedy=True, session=SESSION)
    (line,) = _lines(tmp_path)
    assert line['command_sha256'] == hashlib.sha256(secret.encode('utf-8')).hexdigest()[: walls.DIGEST_CHARS]
    assert 's3cr3t' not in walls.ledger(tmp_path).read_text(encoding='utf-8')
    assert (line['session'], line['rule'], line['remedy_present']) == (SESSION, 'FORGE-WRITE-VIA-HTTP', True)
    assert set(line) == {'ts', 'session', 'rule', 'command_sha256', 'remedy_present'}


@pytest.mark.parametrize(
    ('text', 'expected'),
    [
        (REMEDIED, True),
        ("[targets C:/x, which declares no door; repo files named below are C:/y's]\n" + REMEDIED, True),
        ('BLOCKED', False),
        ('SOME-RULE: refused.\ndetails: docs-src/dev/refusals.md#some-rule', False),
        ('', False),
    ],
)
def test_a_remedy_is_a_line_beyond_the_cause_that_is_not_only_a_pointer(text: str, *, expected: bool) -> None:
    """PLANTED both ways: a one-line refusal, or one whose only second line is ``details:``, names no door."""
    assert walls.has_remedy(text) is expected


def test_a_refusal_lands_in_both_the_metrics_and_the_ledger_through_one_call(tmp_path: Path) -> None:
    walls.refused(tmp_path, repo='r', rule='GIT-STASH', reason='agent-guard', command='git stash', remedy=True)
    assert [line['lab.rule.id'] for line in metrics.read(metrics.REFUSAL, root=tmp_path)] == ['GIT-STASH']
    assert [line['rule'] for line in _lines(tmp_path)] == ['GIT-STASH']


def test_the_engine_door_records_a_digest_it_was_handed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine hashes the command itself and hands only the digest over the command line."""
    monkeypatch.chdir(tmp_path)
    argv = ['refused', '--rule', 'GIT-STASH', '--reason', 'agent-guard', '--command-sha256', 'ab12', '--no-remedy']
    assert walls.main([*argv, '--session', SESSION]) == 0
    (line,) = _lines(tmp_path)
    assert (line['command_sha256'], line['remedy_present'], line['session']) == ('ab12', False, SESSION)


def test_a_session_with_no_unremedied_wall_stops_silently(tmp_path: Path) -> None:
    walls.record(tmp_path, rule='GIT-STASH', command='git stash', remedy=True, session=SESSION)
    walls.record(tmp_path, rule='BLOCKED-X', command='x', remedy=False, session='another-session')
    assert _stop(tmp_path) is None


def test_an_unremedied_wall_blocks_the_stop_once_naming_it_and_the_gap_loop(tmp_path: Path) -> None:
    walls.record(tmp_path, rule='SOME-DOOR', command='x', remedy=False, session=SESSION)
    said = _stop(tmp_path)
    assert said is not None
    assert said['decision'] == 'block'
    reason = str(said['reason'])
    assert reason.startswith(f'{walls.RULE}: ')
    assert 'SOME-DOOR' in reason
    assert 'close the gap: add the row/remedy, or record the gap' in reason
    assert '-m dev_lab.dev.walls close --rule SOME-DOOR --by ' in reason
    assert _stop(tmp_path, again=True) is None


def test_a_closed_wall_no_longer_blocks(tmp_path: Path) -> None:
    walls.record(tmp_path, rule='SOME-DOOR', command='x', remedy=False, session=SESSION)
    walls.close(tmp_path, rule='SOME-DOOR', by='issue#12', session=SESSION)
    assert _stop(tmp_path) is None
    assert walls.open_walls(tmp_path, SESSION) == ()


def test_the_close_door_refuses_an_empty_by(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A closure that names nothing is the route-around this rule exists to refuse."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        walls.main(['close', '--rule', 'SOME-DOOR', '--by', ' ', '--session', SESSION])


def test_a_foreign_denial_seen_after_a_tool_call_is_an_unremedied_wall(tmp_path: Path) -> None:
    """A denial no family emit path saw (a classifier, a tool's own refusal) carries no family pointer."""
    payload = {
        'session_id': SESSION,
        'cwd': str(tmp_path),
        'tool_name': 'Bash',
        'tool_input': {'command': 'rm -rf build'},
        'error': 'Permission to use Bash has been denied by the auto-mode classifier.',
    }
    assert walls.main(['post-tool'], stdin=io.StringIO(json.dumps(payload))) == 0
    (line,) = _lines(tmp_path)
    assert (line['rule'], line['remedy_present'], line['session']) == (walls.UNKNOWN, False, SESSION)


@pytest.mark.parametrize(
    'text',
    [
        REMEDIED,  # a family refusal: already recorded at its own choke point
        'Exit code 1\nAssertionError: 2 != 3',  # an ordinary failure, not a refusal
    ],
)
def test_a_family_refusal_or_an_ordinary_failure_is_not_recorded_twice(tmp_path: Path, text: str) -> None:
    payload = {'session_id': SESSION, 'cwd': str(tmp_path), 'tool_name': 'Bash', 'tool_input': {}, 'error': text}
    assert walls.main(['post-tool'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert not walls.ledger(tmp_path).exists()


def test_a_named_rule_in_a_foreign_denial_is_kept(tmp_path: Path) -> None:
    payload = {
        'session_id': SESSION,
        'cwd': str(tmp_path),
        'tool_response': {'stderr': 'PreToolUse:Bash hook error: OTHER-RULE: blocked', 'stdout': ''},
    }
    assert walls.main(['post-tool'], stdin=io.StringIO(json.dumps(payload))) == 0
    assert [line['rule'] for line in _lines(tmp_path)] == ['OTHER-RULE']
