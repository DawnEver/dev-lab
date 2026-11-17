"""ONE DISPATCHER PER EVENT (dev-lab #640): the rows of WIRING run in one interpreter and answer as one.

Every arm plants handlers -- a module of this file's own, wired through a monkeypatched table -- so each merge rule
is shown saying no as well as yes: a refusal from a row not wired ``may_block`` is passed, a hung row is cut, a
``once`` row runs once per session.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import sys
import time
import types
from collections.abc import Callable
from pathlib import Path

import pytest

from dev_lab.dev import agent_wiring, hookdispatch
from dev_lab.dev.agent_wiring import Wire


def _module(monkeypatch: pytest.MonkeyPatch, name: str, main: object) -> str:
    module = types.ModuleType(name)
    monkeypatch.setattr(module, 'main', main, raising=False)
    monkeypatch.setitem(sys.modules, name, module)
    return name


def _dispatch(monkeypatch: pytest.MonkeyPatch, wires: tuple[Wire, ...], event: str, payload: dict) -> tuple[str, str]:
    """One dispatch of *wires*, the budgets lifted and no runner started.

    These arms test the merge: a loaded box (measured: a swapping one) must not hand a fast row off. A row's own
    ``timeout`` still bounds it.
    """
    monkeypatch.setattr(hookdispatch, 'WIRING', wires)
    monkeypatch.setattr(agent_wiring, 'DISPATCH_BUDGET_S', 60.0)
    monkeypatch.setattr(agent_wiring, 'GUARD_BUDGET_S', 60.0)
    monkeypatch.setattr(hookdispatch.hookhandoff, 'detach', lambda _root, _job: None)
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    assert hookdispatch.main([event]) == 0, 'the dispatcher always exits 0'
    return out.getvalue(), err.getvalue()


def _say(text: str, code: int = 0, *, err: str = '') -> Callable[[list[str]], int]:
    def main(_argv: list[str]) -> int:
        json.load(sys.stdin)  # every handler reads the one payload
        sys.stdout.write(text)
        sys.stderr.write(err)
        return code

    return main


def _deny(reason: str) -> str:
    decision = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': reason}
    return json.dumps({'hookSpecificOutput': decision})


def test_only_a_may_block_row_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the same deny from a row not wired may_block passes, naming itself on stderr."""
    wires = (
        Wire(('PreToolUse',), _module(monkeypatch, 'planted_a', _say(_deny('A refuses'))), may_block=True),
        Wire(('PreToolUse',), _module(monkeypatch, 'planted_b', _say(_deny('B refuses')))),
    )
    out, err = _dispatch(monkeypatch, wires, 'PreToolUse', {'tool_name': 'Bash'})
    said = json.loads(out)['hookSpecificOutput']
    assert (said['permissionDecision'], said['permissionDecisionReason']) == ('deny', 'A refuses')
    assert 'planted_b answered a refusal but is not wired may_block' in err


def test_an_exit_two_blocks_a_stop_and_contexts_join(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exit 2 from a may_block row is a ``decision: block``; another row's exit 2 is a fault, passed."""
    wires = (
        Wire(('Stop',), _module(monkeypatch, 'planted_c', _say('', 2, err='C: unfinished')), may_block=True),
        Wire(('Stop',), _module(monkeypatch, 'planted_d', _say('', 2, err='D: noise'))),
        Wire(('Stop',), _module(monkeypatch, 'planted_e', _say(json.dumps({'systemMessage': 'E note'})))),
    )
    out, err = _dispatch(monkeypatch, wires, 'Stop', {})
    assert json.loads(out) == {'decision': 'block', 'reason': 'C: unfinished', 'systemMessage': 'E note'}
    assert 'planted_d exited 2; not a refusal' in err


def test_prompt_contexts_merge_plain_text_and_json(monkeypatch: pytest.MonkeyPatch) -> None:
    context = json.dumps({'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': 'two'}})
    wires = (
        Wire(('UserPromptSubmit',), _module(monkeypatch, 'planted_f', _say('one\n'))),
        Wire(('UserPromptSubmit',), _module(monkeypatch, 'planted_g', _say(context))),
    )
    out, _err = _dispatch(monkeypatch, wires, 'UserPromptSubmit', {})
    assert json.loads(out) == {
        'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': 'one\ntwo'}
    }


def test_a_row_sees_only_its_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED CONTROL: the shell row answers a Bash call and stays silent on a Write."""
    wires = (
        Wire(('PreToolUse',), _module(monkeypatch, 'planted_h', _say(_deny('h'))), tools=('Bash',), may_block=True),
    )
    assert _dispatch(monkeypatch, wires, 'PreToolUse', {'tool_name': 'Bash'})[0]
    assert _dispatch(monkeypatch, wires, 'PreToolUse', {'tool_name': 'Write'})[0] == ''


def test_a_crash_passes_and_a_hung_row_is_handed_off_naming_themselves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A crash is one stderr line; a row past its bound is handed to the background (HOOK-UNDER-FIVE-SECONDS)."""
    (tmp_path / '.git').mkdir()

    def crash(_argv: list[str]) -> int:
        msg = 'boom'
        raise RuntimeError(msg)

    def hang(_argv: list[str]) -> int:
        time.sleep(30)
        return 2

    wires = (
        Wire(('Stop',), _module(monkeypatch, 'planted_i', crash), may_block=True),
        Wire(('Stop',), _module(monkeypatch, 'planted_j', hang), may_block=True, timeout=1),
    )
    out, err = _dispatch(monkeypatch, wires, 'Stop', {'cwd': str(tmp_path)})
    assert 'RuntimeError: boom' in err
    said = json.loads(out)['systemMessage']
    assert said.startswith('HOOK-UNDER-FIVE-SECONDS: planted_j ran past the hook budget')
    [job] = (tmp_path / '.git' / hookdispatch.hookhandoff.HANDOFF_DIR).glob('*.json')
    assert json.loads(job.read_text(encoding='utf-8'))['rows'] == ['planted_j'], 'queued, never dropped'


def test_a_once_row_runs_once_per_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """PLANTED CONTROL: the row without ``once`` runs again; a new session runs the once row again."""
    (tmp_path / '.git').mkdir()  # the ledger lives in the git dir the payload's cwd lies in
    ran: list[str] = []

    def mark(name: str) -> Callable[[list[str]], int]:
        def main(_argv: list[str]) -> int:
            ran.append(name)
            return 0

        return main

    wires = (
        Wire(('SessionStart',), _module(monkeypatch, 'planted_k', mark('once')), once=True),
        Wire(('SessionStart',), _module(monkeypatch, 'planted_l', mark('every'))),
    )
    for session in ('s1', 's1', 's2'):
        _dispatch(monkeypatch, wires, 'SessionStart', {'session_id': session, 'cwd': str(tmp_path)})
    assert ran == ['once', 'every', 'every', 'once', 'every']


def test_every_wired_handler_exists_in_this_install() -> None:
    """Rows and code are one install: every WIRING module imports and has a ``main``."""
    for wire in agent_wiring.WIRING:
        assert callable(importlib.import_module(wire.module).main), wire.name


def test_the_real_dispatcher_answers_through_the_launcher_command(tmp_path: Path) -> None:
    """End to end in a subprocess: the shipped PreToolUse journal door and write hook pass a harmless call."""
    payload = {'tool_name': 'Write', 'tool_input': {'file_path': str(tmp_path / 'x.txt')}, 'cwd': str(tmp_path)}
    done = subprocess.run(
        [sys.executable, '-m', 'dev_lab.dev.hookdispatch', 'PreToolUse'],
        input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8', check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr


# ------------------------------------------------------------------------------------- a repo's own declared wires

_DENYING_HANDLER = """import json, os, pathlib, sys


def main(argv):
    json.load(sys.stdin)
    pathlib.Path(__file__).with_name('ran-in').write_text(str(os.getpid()), encoding='utf-8')
    decision = {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', 'permissionDecisionReason': 'repo refuses'}
    sys.stdout.write(json.dumps({'hookSpecificOutput': decision}))
    return 0
"""


def _declaring(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: str, row: str) -> Path:
    """A consumer checkout declaring one ``[[tool.dev_lab.agent_hooks]]`` row, its handler a module of its own."""
    root = tmp_path / 'consumer'
    root.mkdir()
    (root / 'pyproject.toml').write_text(f'[[tool.dev_lab.agent_hooks]]\n{row}\n', encoding='utf-8')
    (root / f'{module}.py').write_text(_DENYING_HANDLER, encoding='utf-8')
    monkeypatch.setenv('CLAUDE_PROJECT_DIR', str(root))
    monkeypatch.delitem(sys.modules, module, raising=False)
    return root


def test_a_repo_declared_wire_runs_inside_the_one_dispatcher(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The repo's row is merged into the event's single dispatcher: one interpreter, one joined answer.

    PLANTED CONTROL: a call of a tool the row does not name hears only the family row.
    """
    row = 'events = ["PreToolUse"]\nmodule = "planted_repo_wire_a"\ntools = ["Write"]\nmay_block = true'
    root = _declaring(tmp_path, monkeypatch, 'planted_repo_wire_a', row)
    family = (Wire(('PreToolUse',), _module(monkeypatch, 'planted_m', _say(_deny('family refuses'))), may_block=True),)
    out, _err = _dispatch(monkeypatch, family, 'PreToolUse', {'tool_name': 'Write', 'cwd': str(root)})
    assert json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] == 'family refuses\nrepo refuses'
    assert (root / 'ran-in').read_text(encoding='utf-8') == str(os.getpid()), 'in the dispatcher, not a process'
    out, _err = _dispatch(monkeypatch, family, 'PreToolUse', {'tool_name': 'Bash', 'cwd': str(root)})
    assert json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] == 'family refuses'


def test_an_unimportable_declared_wire_is_refused_by_name_and_the_family_still_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _declaring(tmp_path, monkeypatch, 'planted_repo_wire_b', 'events = ["PreToolUse"]\nmodule = "no_such_wire"')
    with pytest.raises(agent_wiring.WireRefused, match=r'no_such_wire.*not importable'):
        agent_wiring.declared(root)
    family = (Wire(('PreToolUse',), _module(monkeypatch, 'planted_n', _say(_deny('family refuses'))), may_block=True),)
    out, err = _dispatch(monkeypatch, family, 'PreToolUse', {'tool_name': 'Write', 'cwd': str(root)})
    assert json.loads(out)['hookSpecificOutput']['permissionDecisionReason'] == 'family refuses'
    assert 'no_such_wire' in err
    assert 'agent_hooks' in err, 'the refusal names the table to fix'


@pytest.mark.parametrize(
    ('rows', 'said'),
    [
        ('events = ["PreToolUse"]\nmodule = "dev_lab.dev.codeplace"', 'duplicates a family row'),
        (
            (
                'events = ["Stop"]\nmodule = "planted_repo_wire_c"\n\n'
                '[[tool.dev_lab.agent_hooks]]\nevents = ["SessionStart"]\nmodule = "planted_repo_wire_c"'
            ),
            'declared twice',
        ),
        ('events = ["Stop"]\nmodule = "planted_repo_wire_c"\nblocks = true', 'unknown key'),
        ('events = []\nmodule = "planted_repo_wire_c"', 'events'),
        ('events = ["Stop"]\nmodule = "planted_repo_wire_c"\ntimeout = 0', 'timeout'),
    ],
)
def test_a_duplicate_or_malformed_declared_wire_is_refused_by_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rows: str, said: str
) -> None:
    root = _declaring(tmp_path, monkeypatch, 'planted_repo_wire_c', rows)
    with pytest.raises(agent_wiring.WireRefused, match=said):
        agent_wiring.declared(root)


def test_a_well_formed_declared_wire_is_read_as_its_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """PLANTED CONTROL beside the refusals: the same table, well formed, is one Wire with every field carried."""
    row = 'events = ["Stop"]\nmodule = "planted_repo_wire_d"\nargs = ["x"]\nonce = true\ntimeout = 1'
    root = _declaring(tmp_path, monkeypatch, 'planted_repo_wire_d', row)
    assert agent_wiring.declared(root) == (Wire(('Stop',), 'planted_repo_wire_d', ('x',), once=True, timeout=1),)
    assert agent_wiring.declared(tmp_path) == (), 'no pyproject declares nothing'
