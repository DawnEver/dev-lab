"""The agent-guard ENGINE the family ships, and the way a repo reaches it without a hand-copy.

THE GAP THIS CLOSES, MEASURED 2026-09-17. :mod:`lab_commons.dev.hooks` authors the deny REGISTRY and
:mod:`lab_commons.dev.hook_adoption` renders it into the engine's own JSON -- its docstring even
carries the wiring recipe -- but the ENGINE the recipe points at lived in exactly ONE repo
(``motronics-studio/.claude/hooks/deny-commands.js``, wired by a ``PreToolUse`` matcher in that
repo's ``.claude/settings.json``). A ``find`` over the installed ``lab_commons`` returned no ``.js``
at all. So a repo could render a perfectly correct ``deny-rules.json`` and be left with AN INERT
DECLARATION THAT READS AS A GUARD -- precisely the defect the registry exists to remove, arriving
through the registry's own recipe. An agent refused to close its ``AGENT-GUARD`` adoption row for
that reason and was right to.

WHY THE ENGINE STAYS JAVASCRIPT. It is not a language preference: the tool that runs a ``PreToolUse``
hook executes a command line and reads a JSON decision from its stdout, and the shipped engine is the
one whose behaviour has been MEASURED against real evasions (see its own header). Re-implementing
"what will this shell line actually execute" in Python would be a second implementation of the one
decision this family most needs a single answer to -- the fork these modules exist to remove. So the
engine moves VERBATIM, minus a provenance stamp, and nothing about its behaviour is re-decided here.

WHY A PAYLOAD SUBPACKAGE -- the shape :mod:`lab_commons.dev.githooks` already proved. A data file
inside a package directory travels in the wheel; a loose script beside ``src/`` does not. And
:data:`ENGINES` is DERIVED from the directory, so an engine that is added is shipped and one that is
deleted stops being advertised, rather than either being a list somebody maintains.

WHERE THIS DIFFERS FROM ``githooks``, AND WHY -- the one place the precedent does not fit, stated
because following it blindly would have produced a guard that is slower on EVERY tool call. A git
hook is reached by NAME through the interpreter (``python -m lab_commons.dev.githooks bump-version``)
and never copied. A ``PreToolUse`` hook cannot take that route:

* it runs on every single Bash tool call, and an interpreter start per call to locate a file is a
  tax on the whole session rather than on a commit;
* its command line lives in ``.claude/settings.json``, which is committed in the consuming repo and
  read on other boxes -- so an absolute ``site-packages`` path there is FALSE everywhere but the box
  that wrote it.

So the engine is INSTALLED into the consuming repo and the anti-drift property is bought a different
way: the copy carries :data:`STAMP`, and :mod:`lab_commons.dev.agent_guard` compares the installed
bytes against the shipped ones -- so a drifted copy is a REPORTED finding rather than an invisible
fork, and re-installing refreshes it. A copy that is checked is not the copy this family refuses; an
unchecked one is.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

__all__ = [
    'ENGINES',
    'ENGINE_SUFFIX',
    'STAMP',
    'EngineNotReadable',
    'EngineNotShipped',
    'NoNode',
    'decide',
    'engine_path',
    'engine_source',
    'main',
    'node_executable',
    'run_engine',
]

#: Every shipped engine is JavaScript; the suffix is what :data:`ENGINES` is derived through.
ENGINE_SUFFIX: Final = '.js'

#: The provenance line every shipped engine carries, and the ONE string an installed copy is
#: recognised by. Its absence in an occupied slot means somebody else's engine is there -- a
#: DIFFERENT finding from "stale", because re-installing would DELETE a hand-written file rather
#: than refresh a managed one. The same distinction :mod:`lab_commons.dev.hook_install` draws from
#: pre-commit's own marker, for the same reason.
STAMP: Final = 'Engine shipped by lab-commons: lab_commons.dev.agenthooks'

#: The engine reads a payload and writes a decision; nothing here waits on a network or an editor.
_ENGINE_TIMEOUT_S: Final = 60

_HERE: Final = Path(__file__).resolve().parent

#: The shipped engines, BY NAME, derived from the directory rather than written down.
ENGINES: Final[tuple[str, ...]] = tuple(sorted(p.stem for p in _HERE.glob(f'*{ENGINE_SUFFIX}')))


class EngineNotShipped(LookupError):
    """An engine was asked for by a name this package does not ship."""


class EngineNotReadable(OSError):
    """The engine or the rules file named for a run is not there.

    RAISED RATHER THAN FALLEN BACK FROM, and that is the whole point of naming an engine by PATH. The
    engine fails OPEN by construction, so "run something else instead" and "run nothing" both reach a
    caller as ``None`` -- an allowed command. A silent substitution of the wheel's copy for an absent
    consumer copy would therefore report the consumer's engine as agreeing with the family on every
    probe at exactly the moment the consumer has no engine at all.
    """


class NoNode(RuntimeError):
    """No ``node`` could be resolved on this box.

    ASSERTED RATHER THAN SKIPPED, for the reason :class:`lab_commons.dev.githooks.NoBash` gives: the
    hook entry starts with ``node``, so a box without one runs NO guard at all while every repo on
    it still reads as guarded. That is the finding, not a reason to report success.
    """


def engine_path(name: str = 'deny-commands') -> Path:
    """The absolute path of a shipped engine, as installed in this interpreter's ``lab_commons``.

    Raises:
        EngineNotShipped: When *name* is not in :data:`ENGINES`.

    """
    candidate = _HERE / f'{name}{ENGINE_SUFFIX}'
    if name not in ENGINES or not candidate.is_file():
        msg = f'{name!r} is not an engine this package ships; shipped: {", ".join(ENGINES) or "(none)"}'
        raise EngineNotShipped(msg)
    return candidate


def engine_source(name: str = 'deny-commands') -> str:
    """The shipped engine's text -- what an installed copy is compared AGAINST, read once here."""
    return engine_path(name).read_text(encoding='utf-8')


def node_executable() -> str:
    """Resolve ``node`` on ``PATH``.

    Raises:
        NoNode: When it does not resolve.

    """
    found = shutil.which('node')
    if found:
        return found
    msg = 'no `node` on PATH; this box can run no agent-guard hook, so every repo on it is unguarded'
    raise NoNode(msg)


def run_engine(engine: Path, command: str, rules: Path, *, cwd: Path | None = None) -> str | None:
    """THE ONE RUNNER. Drive the engine AT *engine* over one Bash command; the reason, or ``None``.

    THE ENGINE IS DRIVEN, NEVER MODELLED. This feeds the real hook payload on stdin exactly as the
    tool does and reads the real decision off stdout, so a test built on it is testing a file that
    will really run rather than a Python restatement of what it is believed to do.

    AN ENGINE IS NAMED BY A PATH WHENEVER THE QUESTION IS *WHOSE COPY*, and this function is why
    there is one spelling of that rather than two. Two runners existed until 2026-09-17 -- this
    module's :func:`decide`, which takes a shipped engine NAME and so always judges the wheel's copy,
    and a hand-rolled ``subprocess`` call in :mod:`lab_commons.dev.famtests.agentguard`, which takes
    a repo root and so judges the installed copy. Same package, opposite answers to *which file is
    the subject*, and a consumer measured that contradiction rather than adopting either body. The
    two copies DRIFT: measured 2026-09-17, the engines installed in three repos were stale enough to
    ALLOW the heredoc-wrapped test invocation the shipped one had refused since 2026-08-22. They
    agree today because somebody reinstalled, not because they cannot differ.

    Args:
        engine: the ``deny-commands.js`` to run -- a consumer's installed copy, or
            :func:`engine_path` for the one this wheel ships. Say which; never guess.
        command: the Bash command line the agent asked for.
        rules: the ``deny-rules.json`` to judge it against.
        cwd: the tool call's working directory, which the engine expands into ``{root}``.

    Returns:
        The ``permissionDecisionReason`` when the engine denies, else ``None``. The engine fails OPEN
        by construction -- unparseable input or a bad rule prints nothing -- and that shows up here
        as ``None``, which is the truthful answer: nothing was refused.

    Raises:
        EngineNotReadable: either path is not a file. See that class for why this is not a fallback.

    """
    for path in (engine, rules):
        if not path.is_file():
            msg = f'{path} is not a file, so nothing judged {command!r} -- and nothing else may judge it instead'
            raise EngineNotReadable(msg)
    payload = {
        'tool_name': 'Bash',
        'tool_input': {'command': command},
        'cwd': str(cwd) if cwd is not None else '',
    }
    done = subprocess.run(
        [node_executable(), str(engine), str(rules)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=_ENGINE_TIMEOUT_S,
    )
    if not done.stdout.strip():
        return None
    decision = json.loads(done.stdout)['hookSpecificOutput']
    return decision['permissionDecisionReason'] if decision.get('permissionDecision') == 'deny' else None


def decide(command: str, rules: Path, *, cwd: Path | None = None, engine: str = 'deny-commands') -> str | None:
    """Run THE WHEEL'S OWN copy of a shipped engine over one Bash command; the reason, or ``None``.

    THE SUBJECT IS THE WHEEL, AND THAT IS THE ONLY QUESTION THIS ANSWERS: *does the engine this
    family ships refuse this shape?* A body asking about a CHECKOUT wants :func:`run_engine` with
    that checkout's own ``.claude/hooks/deny-commands.js`` -- the installed copy drifts, and the
    measurement is in :func:`run_engine`. A shipped NAME is what makes a call read as a family
    question; a PATH is what makes it read as a repo question.

    Args:
        command: the Bash command line the agent asked for.
        rules: the ``deny-rules.json`` to judge it against.
        cwd: the tool call's working directory, which the engine expands into ``{root}``.
        engine: which SHIPPED engine to run, by name.

    Returns:
        What :func:`run_engine` returns for the shipped engine of that name.

    Raises:
        EngineNotShipped: no engine of that name is in this wheel.

    """
    return run_engine(engine_path(engine), command, rules, cwd=cwd)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.agenthooks`` -- locate a shipped engine, or ASK it about a command.

    The ``--check`` arm exists so "would this be refused here?" is answerable without installing
    anything and without hand-building a hook payload: it is the same function the suite drives.
    """
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.agenthooks',
        description='Locate, or drive, the agent-guard engine shipped by lab-commons.',
    )
    parser.add_argument('engine', nargs='?', default='deny-commands', help=f'which engine ({", ".join(ENGINES)})')
    parser.add_argument('--path', action='store_true', help='print the engine path (the default action)')
    parser.add_argument('--list', action='store_true', help='print every shipped engine, one per line')
    parser.add_argument('--check', metavar='COMMAND', help='ask the engine whether it denies COMMAND')
    parser.add_argument('--rules', type=Path, help='the deny-rules.json --check judges against')
    parsed = parser.parse_args(argv)

    if parsed.list:
        sys.stdout.write('\n'.join(ENGINES) + '\n')
        return 0
    if parsed.check is not None:
        if parsed.rules is None:
            parser.error('--check needs --rules: the engine has no rules of its own, and that is the design')
        reason = decide(parsed.check, parsed.rules, cwd=Path.cwd(), engine=parsed.engine)
        if reason is None:
            sys.stdout.write('[agent-guard] ALLOWED -- no shipped rule names this command\n')
            return 0
        sys.stdout.write(f'[agent-guard] DENIED -- {reason}\n')
        return 1
    sys.stdout.write(f'{engine_path(parsed.engine)}\n')
    return 0
