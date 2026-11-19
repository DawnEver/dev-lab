"""HOOK-UNDER-FIVE-SECONDS (user ruling D24, 2026-11-17): a rendered hook is bounded; slow work runs in the background.

Every rendered hook is bounded at five seconds, and work that can take longer runs to completion in the background
instead of being cut or skipped. Every arm plants its own rows, so each rule is shown saying no as well as yes: a
rendered timeout of 30 is caught, an inline wire bounded past the budget is refused, a slow row is handed off rather
than dropped, and a guard's refusal is never deferred.
"""

from __future__ import annotations

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
from lab_commons.liveness import creation_stamp

from dev_lab.dev import agent_guard, agent_wiring, hookdispatch, hookhandoff
from dev_lab.dev.agent_wiring import HOOK_TIMEOUT_S, Wire, WireRefused


def _over_ceiling(settings: dict) -> list[str]:
    """Every hook entry of *settings* with no timeout, or one above the ceiling, as ``<event>: <command>``."""
    return [
        f'{event}: {hook.get("command")}'
        for event, entries in settings.get('hooks', {}).items()
        for entry in entries
        for hook in entry['hooks']
        if not isinstance(hook.get('timeout'), int) or not 0 < hook['timeout'] <= HOOK_TIMEOUT_S
    ]


def _declare(root: Path, module: str, row: str, body: str = 'def main(argv):\n    return 0\n') -> Path:
    root.mkdir(exist_ok=True)
    (root / '.git').mkdir(exist_ok=True)
    manifest = root / 'pyproject.toml'
    before = manifest.read_text(encoding='utf-8') if manifest.is_file() else ''
    manifest.write_text(f'{before}[[tool.dev_lab.agent_hooks]]\nmodule = "{module}"\n{row}\n', encoding='utf-8')
    (root / f'{module}.py').write_text(body, encoding='utf-8')
    return root


def test_every_rendered_hook_row_carries_a_timeout_within_the_ceiling(tmp_path: Path) -> None:
    """THE RATCHET over the real renderer, family and repo-declared rows alike.

    PLANTED CONTROL: a row bounded at 30 and a row with no bound are both caught by the same reader.
    """
    assert HOOK_TIMEOUT_S == 5
    repo = _declare(tmp_path / 'repo', 'planted_budget_wire_a', 'events = ["PreCompact"]')
    for settings in (agent_guard.wire_settings({}), agent_guard.wire_settings({}, repo)):
        assert settings['hooks'], 'the renderer rendered nothing, so the ratchet read nothing'
        assert _over_ceiling(settings) == []
    planted = {'hooks': {'Stop': [{'hooks': [{'command': 'slow', 'timeout': 30}, {'command': 'unbounded'}]}]}}
    assert _over_ceiling(planted) == ['Stop: slow', 'Stop: unbounded']


def test_an_inline_wire_bounded_past_the_budget_is_refused_and_a_detached_one_is_not() -> None:
    """PLANTED CONTROL: the same bound of 30 is a legal background bound; a short inline bound is legal too."""
    with pytest.raises(WireRefused, match=r'^HOOK-UNDER-FIVE-SECONDS:.*\n.*detached.*\ndetails: '):
        Wire(('Stop',), 'planted', timeout=30)
    assert Wire(('Stop',), 'planted', timeout=30, detached=True).background_bound == 30
    assert Wire(('Stop',), 'planted', timeout=1).inline_bound == 1
    assert Wire(('Stop',), 'planted').inline_bound == agent_wiring.DISPATCH_BUDGET_S


def test_a_detached_wire_cannot_refuse() -> None:
    """A guard's answer is needed now: a background row cannot block. PLANTED CONTROL: an inline guard is legal."""
    with pytest.raises(WireRefused, match='HOOK-UNDER-FIVE-SECONDS'):
        Wire(('Stop',), 'planted', may_block=True, detached=True)
    assert Wire(('Stop',), 'planted', may_block=True).may_block


def test_every_family_guard_runs_inline() -> None:
    assert [w.name for w in agent_wiring.WIRING if w.may_block and w.detached] == []
    assert any(w.detached for w in agent_wiring.WIRING), 'no row is detached, so the arm reads nothing'


@pytest.mark.parametrize(
    ('row', 'refused'),
    [('events = ["Stop"]\ntimeout = 30', True), ('events = ["Stop"]\ntimeout = 30\ndetached = true', False)],
)
def test_a_declared_row_meets_the_same_bound(tmp_path: Path, row: str, *, refused: bool) -> None:
    root = _declare(tmp_path / 'repo', f'planted_budget_wire_{int(refused)}', row)
    sys.modules.pop(f'planted_budget_wire_{int(refused)}', None)
    if refused:
        with pytest.raises(WireRefused, match='HOOK-UNDER-FIVE-SECONDS'):
            agent_wiring.declared(root)
    else:
        assert agent_wiring.declared(root)[0].detached


# ------------------------------------------------------------------------------------- in process: hand-offs


def _module(monkeypatch: pytest.MonkeyPatch, name: str, main: Callable[[list[str]], int]) -> str:
    module = types.ModuleType(name)
    monkeypatch.setattr(module, 'main', main, raising=False)
    monkeypatch.setitem(sys.modules, name, module)
    return name


def _quiet(text: str = '', pause: float = 0.0) -> Callable[[list[str]], int]:
    def main(_argv: list[str]) -> int:
        time.sleep(pause)
        sys.stdout.write(text)
        return 0

    return main


def _dispatch(
    monkeypatch: pytest.MonkeyPatch, wires: tuple[Wire, ...], argv: list[str], payload: dict, *, budget: float = 60.0
) -> tuple:
    """One in-process dispatch; *budget* lifted by default, so a loaded box hands nothing off the arm did not plant."""
    handed: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(hookdispatch, 'WIRING', wires)
    monkeypatch.setattr(agent_wiring, 'DISPATCH_BUDGET_S', budget)
    monkeypatch.setattr(agent_wiring, 'GUARD_BUDGET_S', max(budget, agent_wiring.GUARD_BUDGET_S))
    monkeypatch.setattr(hookhandoff, 'detach', lambda root, path: handed.append((str(root), path)))
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, 'stdout', out)
    monkeypatch.setattr(sys, 'stderr', err)
    assert hookdispatch.main(argv) == 0
    return out.getvalue(), err.getvalue(), handed


def test_a_detached_row_is_handed_off_and_an_inline_one_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    wires = (
        Wire(('SessionStart',), _module(monkeypatch, 'planted_bg', _quiet('late')), detached=True),
        Wire(('SessionStart',), _module(monkeypatch, 'planted_fg', _quiet('now'))),
    )
    out, _err, handed = _dispatch(monkeypatch, wires, ['SessionStart'], {'session_id': 's', 'cwd': str(tmp_path)})
    assert json.loads(out)['hookSpecificOutput']['additionalContext'] == 'now'
    [(_root, path)] = handed
    assert json.loads(Path(path).read_text(encoding='utf-8'))['rows'] == ['planted_bg']


def test_the_budget_hands_the_rest_to_the_background_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A row past the budget and every row after it run in the background -- never skipped.

    PLANTED CONTROL: with the full budget both rows run inline and nothing is handed off.
    """
    (tmp_path / '.git').mkdir()
    wires = (
        Wire(('Stop',), _module(monkeypatch, 'planted_slow', _quiet(pause=1.0))),
        Wire(('Stop',), _module(monkeypatch, 'planted_next', _quiet())),
    )
    payload = {'session_id': 's', 'cwd': str(tmp_path)}
    out, _err, handed = _dispatch(monkeypatch, wires, ['Stop'], payload, budget=0.3)
    [(_root, path)] = handed
    assert json.loads(Path(path).read_text(encoding='utf-8'))['rows'] == ['planted_slow', 'planted_next']
    said = json.loads(out)['systemMessage']
    assert said.startswith('HOOK-UNDER-FIVE-SECONDS:')
    assert 'planted_slow' in said
    assert 'planted_next' in said
    assert _dispatch(monkeypatch, wires, ['Stop'], payload)[2] == []


def test_a_background_run_defers_its_answer_to_the_next_prompt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The handed-off rows run; their context reaches the session once, at its next context event.

    PLANTED CONTROL: a guard's refusal run in the background is a note, never a block of a later call.
    """
    (tmp_path / '.git').mkdir()
    deny = json.dumps({'decision': 'block', 'reason': 'too late to refuse'})
    wires = (
        Wire(('SessionStart',), _module(monkeypatch, 'planted_note', _quiet('venv is behind')), detached=True),
        Wire(('Stop',), _module(monkeypatch, 'planted_guard', _quiet(deny)), may_block=True),
    )
    payload = {'session_id': 's9', 'cwd': str(tmp_path)}
    handed = _dispatch(monkeypatch, wires, ['SessionStart'], payload)[2]
    _dispatch(monkeypatch, wires, ['--background', handed[0][1]], {})
    assert not Path(handed[0][1]).exists(), 'the hand-off file is consumed'
    hookhandoff.hand_off(tmp_path, 'Stop', json.dumps(payload), (wires[1],))
    path = next((tmp_path / '.git' / hookhandoff.HANDOFF_DIR).glob('*.json'))
    _dispatch(monkeypatch, wires, ['--background', str(path)], {})
    out = _dispatch(monkeypatch, wires, ['UserPromptSubmit'], payload)[0]
    context = json.loads(out)['hookSpecificOutput']['additionalContext']
    assert 'venv is behind' in context
    assert 'too late to refuse' in context
    assert 'decision' not in json.loads(out)
    assert _dispatch(monkeypatch, wires, ['UserPromptSubmit'], payload)[0] == '', 'delivered once'


def test_the_timing_readout_names_every_row(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / '.git').mkdir()
    wires = (Wire(('Stop',), _module(monkeypatch, 'planted_timed', _quiet())),)
    err = _dispatch(monkeypatch, wires, ['--timing', 'Stop'], {'session_id': 's', 'cwd': str(tmp_path)})[1]
    assert '[hook-timing] Stop planted_timed ' in err
    assert '[hook-timing] Stop total ' in err
    assert '[hook-timing]' not in _dispatch(monkeypatch, wires, ['Stop'], {'cwd': str(tmp_path)})[1]


# ------------------------------------------------------------------------------------- end to end


_SLOW = """import json, pathlib, sys, time


def main(argv):
    json.load(sys.stdin)
    time.sleep({pause})
    pathlib.Path(__file__).with_name('{marker}').write_text('done', encoding='utf-8')
    return 0
"""


def test_slow_work_completes_in_the_background_while_the_hook_returns_under_budget(tmp_path: Path) -> None:
    """PLANTED: an inline row sleeping past the budget and a detached row sleeping past the ceiling.

    The dispatcher returns inside the ceiling; both markers appear afterwards, so neither was dropped.
    """
    root = tmp_path / 'consumer'
    event = 'PreCompact'  # an event the family serves no row on, so only the planted rows run
    _declare(root, 'planted_slow_inline', f'events = ["{event}"]', _SLOW.format(pause=5, marker='inline-done'))
    _declare(root, 'planted_slow_bg', f'events = ["{event}"]\ndetached = true', _SLOW.format(pause=6, marker='bg-done'))
    payload = {'session_id': 'e2e', 'cwd': str(root), 'hook_event_name': event}
    began = time.monotonic()
    done = subprocess.run(
        [sys.executable, '-m', 'dev_lab.dev.hookdispatch', event],
        input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8', check=False, cwd=root,
        env={**os.environ, 'CLAUDE_PROJECT_DIR': str(root)}, timeout=60,
    )  # fmt: skip
    took = time.monotonic() - began
    assert done.returncode == 0, done.stderr
    assert took < HOOK_TIMEOUT_S, f'the hook took {took:.1f} s'
    assert 'planted_slow_inline' in json.loads(done.stdout)['systemMessage']
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline and not all((root / m).is_file() for m in ('inline-done', 'bg-done')):
        time.sleep(0.25)
    assert (root / 'inline-done').is_file(), 'the inline row past the budget was dropped'
    assert (root / 'bg-done').is_file(), 'the detached row never ran'


#: THE MEASUREMENT BOUND, per event, end to end (interpreter start included): generous for a loaded CI box, and still
#: well inside the five seconds every hook source on the event shares. Measured on a Windows workstation 2026-11-17
#: the dispatcher ran 0.3-0.9 s per event warm; a regression to the 2-30 s measured before D24 reds here.
EVENT_BOUND_S = 3.0


def _payload(event: str, root: Path) -> dict:
    payload = {'session_id': f'timed-{event}', 'cwd': str(root), 'hook_event_name': event, 'stop_hook_active': False}
    if event == 'PreToolUse':
        payload |= {'tool_name': 'Write', 'tool_input': {'file_path': str(root / 'notes.txt'), 'content': 'x'}}
    if event.startswith('PostToolUse'):
        payload |= {'tool_name': 'Bash', 'tool_input': {'command': 'echo hi'}, 'tool_response': {'stderr': ''}}
    return payload


@pytest.mark.parametrize('event', agent_wiring.events())
def test_every_event_dispatches_within_its_bound(tmp_path: Path, event: str) -> None:
    """Every event of the family wiring, on a planted payload, in a fresh interpreter, inside :data:`EVENT_BOUND_S`.

    A live runner is planted on the queue (this test's own process), so a detached row is queued and no background
    run starts: the edge "a runner already runs" -- and nothing machine-wide is started by a test.
    PLANTED CONTROL: the queued job proves the event's detached rows were handed off rather than run inline.
    """
    root = tmp_path / 'repo'
    queue = root / '.git' / hookhandoff.HANDOFF_DIR
    queue.mkdir(parents=True)

    me = {'pid': os.getpid(), 'created': creation_stamp(os.getpid())}
    (queue / hookhandoff.RUNNER_LOCK).write_text(json.dumps(me), encoding='utf-8')
    began = time.monotonic()
    done = subprocess.run(
        [sys.executable, '-m', 'dev_lab.dev.hookdispatch', event],
        input=json.dumps(_payload(event, root)), capture_output=True, text=True, encoding='utf-8', check=False,
        cwd=root, env={**os.environ, 'CLAUDE_PROJECT_DIR': str(root)}, timeout=60,
    )  # fmt: skip
    took = time.monotonic() - began
    assert done.returncode == 0, done.stderr
    assert took < EVENT_BOUND_S, f'{event} took {took:.2f} s'
    detached = [wire.name for wire in agent_wiring.WIRING if event in wire.events and wire.detached]
    queued = [json.loads(job.read_text(encoding='utf-8'))['rows'] for job in queue.glob('*.json')]
    assert queued == ([detached] if detached else [])


#: What the dispatcher and its inline rows may not import: each measured on the hook path before D24 (the box ledger
#: through the package's eager re-exports, ~0.5 s; the supervisor and the forge client through the prompt's readers).
_HEAVY = ('lab_commons.box', 'dev_lab.dev.hook_adoption', 'dev_lab.supervise.alert', 'dev_lab.dev.forge')


def _imported(*modules: str) -> set[str]:
    probe = f'import sys\nimport {", ".join(modules)}\nprint("\\n".join(sys.modules))'
    done = subprocess.run(
        [sys.executable, '-c', probe], capture_output=True, text=True, encoding='utf-8', check=True, timeout=120
    )
    return set(done.stdout.split())


def test_the_hook_path_imports_nothing_heavy() -> None:
    """The dispatcher, the hand-off and every INLINE row import none of :data:`_HEAVY`.

    PLANTED CONTROL: the deny-row module the package used to import eagerly does pull the box ledger in.
    """
    inline = sorted({wire.module for wire in agent_wiring.WIRING if not wire.detached})
    loaded = _imported('dev_lab.dev.hookdispatch', 'dev_lab.dev.hookhandoff', *inline)
    assert sorted(loaded & set(_HEAVY)) == []
    assert 'lab_commons.box' in _imported('dev_lab.dev.hook_adoption')
