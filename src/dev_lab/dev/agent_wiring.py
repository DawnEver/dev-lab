"""The hook WIRING, as data: the engine's paths and command, and the ONE table of handlers per event.

:mod:`dev_lab.dev.agent_guard` renders :func:`rows` into settings; :mod:`dev_lab.dev.hookdispatch` reads
:func:`wiring` at run time. Both read the same installed table, so a settings row never names a handler the
interpreter running it lacks.

A REPO ADDS ITS OWN HANDLERS AS DATA (:func:`declared`): ``[[tool.dev_lab.agent_hooks]]`` rows in its
``pyproject.toml``, one :class:`Wire` each (``events``, ``module``, ``args``, ``tools``, ``may_block``, ``once``,
``timeout``). They join the family's rows in the event's one dispatcher -- no settings row, no second process -- so
the wiring has two sources and no third: :data:`WIRING` and the repo's declaration. A declared module must import
from the repo's venv with the repo's root on the path, and a row may not repeat a family row or another declared one
(a row's :attr:`Wire.name` is its identity); either is refused by name (:class:`WireRefused`).
"""

from __future__ import annotations

import contextlib
import importlib.util
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = [
    'DECLARED_TABLE',
    'DISPATCH_MODULE',
    'ENGINE_REL',
    'HOOK_COMMAND',
    'LAUNCHER_REL',
    'REINSTALL_COMMAND',
    'RULES_REL',
    'SETTINGS_REL',
    'SHELL_TOOLS',
    'WIRING',
    'WRITE_TOOLS',
    'Row',
    'Wire',
    'WireRefused',
    'declared',
    'dispatch_command',
    'events',
    'import_root',
    'rows',
    'wiring',
]


#: Repo-relative locations. RELATIVE on purpose: ``.claude/settings.json`` is committed and read on
#: other boxes, so an absolute ``site-packages`` path in the hook command would be true on exactly
#: one machine. These are the spellings consumer-a already uses, so the one repo that was
#: guarded before this module existed verifies as installed rather than as a variant.
ENGINE_REL: Final = '.claude/hooks/deny-commands.js'
RULES_REL: Final = '.claude/hooks/deny-rules.json'
SETTINGS_REL: Final = '.claude/settings.json'

#: THE ONE DOOR a hook reaches this checkout's interpreter through: a node launcher that resolves the venv
#: per platform (and the main checkout's from a linked worktree). A hook spelling ``.venv`` inline drifts
#: from it -- a downstream repo pins that (``test_no_hook_spells_its_own_interpreter``). A repo's own launcher at
#: this path is kept: the install writes it only where none is.
LAUNCHER_REL: Final = '.claude/hooks/py.js'

#: The hook command line, DERIVED from the two paths above rather than spelled twice -- the lesson
#: :data:`dev_lab.dev.hook_install.INSTALL_COMMAND` records: a restatement of a path is a place
#: for the real one to move away from. ANCHORED ON ``$CLAUDE_PROJECT_DIR`` (2026-10-20): the tool runs
#: a hook in the SESSION's cwd, and a cwd-relative engine path from a cwd holding no
#: ``.claude/hooks/`` exits 1 on MODULE_NOT_FOUND -- a NON-BLOCKING hook error, so every command ran
#: unjudged. The variable is the tool's own, so the committed line stays true on every box.
#: AND IT FAILS CLOSED (2026-10-21): a missing engine, a missing ``node`` or an engine that crashed exits
#: nonzero-but-not-2, which the tool reads as a NON-BLOCKING error -- the same fail-open by another door.
#: So the line is a POSIX wrapper: any engine exit but 0 exits 2 (blocking) naming why.
#: ONE POLICY FOR A MISSING PART (dev-lab #639): no engine and no rules are the same broken guard -- the repair
#: (:data:`REINSTALL_COMMAND`, one plain command matched by :data:`_REPAIR_CHECK`) passes, everything else is refused
#: naming it. The repair always passes, engine or not: a guard that refuses its own reinstall has no door.
REINSTALL_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.agent_guard --install'

#: Exit 0 when the hook payload's command is the reinstall alone: an interpreter or the launcher, the module, and
#: ``--install [--force]`` -- no shell operator or newline, so nothing rides along with the repair.
_REPAIR_CHECK: Final = (
    r"""node -e 'let s="";process.stdin.on("data",(d)=>s+=d).on("end",()=>{let c="";"""
    r"""try{c=String(JSON.parse(s).tool_input.command||"")}catch{}"""
    r"""process.exit(/^[^;&|<>`()\n\r]*-m dev_lab\.dev\.agent_guard --install( --force)?$/.test(c.trim())?0:1)})'"""
)
HOOK_COMMAND: Final = (
    f'e="$CLAUDE_PROJECT_DIR/{ENGINE_REL}"; r="$CLAUDE_PROJECT_DIR/{RULES_REL}"; i=$(cat); '
    f'case "$i" in *"agent_guard --install"*) printf %s "$i" | {_REPAIR_CHECK} && exit 0;; esac; '
    '[ -f "$e" ] && [ -f "$r" ] || { echo "agent-guard: no engine at $e or no rules at $r -- refused (fail closed); '
    'repair: ' + REINSTALL_COMMAND.replace('"', '\\"') + '" >&2; exit 2; }; '
    'printf %s "$i" | node "$e" "$r" || '
    '{ echo "agent-guard: the engine exited $? -- refused (fail closed)" >&2; exit 2; }'
)


#: The tools that issue a command line. A rule about a COMMAND can only be enforced where a command
#: is issued, and BOTH shell tools issue one: until 2026-10-08 the matcher named Bash alone, and every
#: denied shape ran unjudged through the PowerShell tool.
SHELL_TOOLS: Final = ('Bash', 'PowerShell')

#: The tools that write a file by path: the :mod:`dev_lab.dev.codeplace` write hook judges each one's target.
WRITE_TOOLS: Final = ('Write', 'Edit', 'MultiEdit', 'NotebookEdit')

#: THE ONE DISPATCHER (:mod:`dev_lab.dev.hookdispatch`, dev-lab #640): settings carry one row per event naming only
#: the event; the dispatcher reads :data:`WIRING` from the INSTALLED package and runs every handler in one
#: interpreter. A handler added to WIRING never reaches a machine whose venv lacks it -- the rows and the code come
#: from the same install -- and a venv predating the dispatcher itself is the launcher's named stale-venv line.
DISPATCH_MODULE: Final = 'dev_lab.dev.hookdispatch'


def dispatch_command(event: str) -> str:
    """The settings command for *event*: the launcher, the dispatcher, the event -- nothing a release can move."""
    return f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m {DISPATCH_MODULE} {event}'


@dataclass(frozen=True, slots=True)
class Wire:
    """One handler the dispatcher runs -- ``python -m <module> <argv>``, in-process -- on each of *events*.

    ``tools``: the tools whose calls a tool event's handler sees (empty: every call). ``may_block``: only such a
    row's refusal (exit 2, ``decision: block``, ``permissionDecision: deny``) is answered; another row's is a wiring
    fault, demoted to one stderr line. ``once``: at most once per session. ``timeout`` (seconds) bounds the row; the
    event's settings row carries the sum, since the dispatcher runs its rows one after another.
    """

    events: tuple[str, ...]
    module: str
    argv: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    may_block: bool = False
    once: bool = False
    timeout: int = 30

    @property
    def name(self) -> str:
        """The row as one readable id: ``<module> <argv>``."""
        return ' '.join((self.module, *self.argv))


_STOPS: Final = ('Stop', 'SubagentStop')

#: THE WIRING, ONE TABLE, AND EACH CHECK HAS ONE TRIGGER. Before every shell call: the journal door
#: (TRACKED-CITES-NO-EPHEMERAL, dev-lab#419); before every write: the codeplace write hook (a report under output/, a
#: write-prone root, a consent file refused; a misplaced code file hinted). After every shell call, succeeded or
#: failed: the wall ledger's foreign-denial reader (WALLS-ARE-RECORDED). Each prompt: the host-pressure reminder (D54),
#: the task binder (D5), the PR inbox -- the ONE machine PR watcher (SESSION-HEARS-ITS-PRS). Every stop, the main
#: session's and each subagent's: the hand-back check and the wall ledger's stop; the main session's adds the stray
#: census, the scratch census and the shell reaper -- Stop is the one event that recurs inside a session, so it is the
#: reaper's clock, and a session's first stop sweeps what an ended one left (measured 2026-11-16: 37 sweeps and both
#: over-bound stops of the day fell in an 11-hour window with no session start). Session start: the ONE reclaim, the
#: machine-file notice (once: drift cannot change within a turn), the venv follower, the forge-token notice, the
#: scratch baseline, the classifier render and the PR watcher.
WIRING: Final = (
    Wire(('PreToolUse',), 'dev_lab.dev.journaldoor', tools=SHELL_TOOLS, may_block=True),
    Wire(('PreToolUse',), 'dev_lab.dev.codeplace', tools=WRITE_TOOLS, may_block=True),
    Wire(('PostToolUse', 'PostToolUseFailure'), 'dev_lab.dev.walls', ('post-tool',), tools=SHELL_TOOLS),
    Wire(('UserPromptSubmit',), 'dev_lab.dev.hostalarm', ('hook',)),
    Wire(('UserPromptSubmit',), 'dev_lab.dev.taskbinding', ('bind',)),
    Wire(('UserPromptSubmit',), 'dev_lab.dev.prwatcher', ('inbox',)),
    Wire(('Stop',), 'dev_lab.dev.codeplace', ('stray',), may_block=True, timeout=60),
    Wire(_STOPS, 'dev_lab.dev.handback', may_block=True, timeout=60),
    Wire(('Stop',), 'dev_lab.dev.scratch', ('stop',), may_block=True, timeout=60),
    Wire(_STOPS, 'dev_lab.dev.walls', ('stop',), may_block=True, timeout=60),
    Wire(('Stop',), 'dev_lab.dev.shellreaper', ('--hook',), timeout=60),
    Wire(('SessionStart',), 'dev_lab.dev.reclaimrun', ('--session-start',), once=True, timeout=120),
    Wire(('SessionStart',), 'dev_lab.dev.devhost', ('session-start',), once=True, timeout=60),
    Wire(('SessionStart',), 'dev_lab.dev.venvfollow', ('--session-start',), timeout=120),
    Wire(('SessionStart',), 'dev_lab.dev.forgeauthnotice', ('--session-start',), once=True, timeout=120),
    Wire(('SessionStart',), 'dev_lab.dev.scratch', ('snapshot',), once=True, timeout=120),
    Wire(('SessionStart',), 'dev_lab.dev.automode', ('session-start',), timeout=120),
    Wire(('SessionStart',), 'dev_lab.dev.prwatcher', ('session-start',), timeout=120),
)


@dataclass(frozen=True, slots=True)
class Row:
    """One rendered settings row: its event, its matcher (``None``: every call), its command and its timeout."""

    event: str
    matcher: str | None
    command: str
    timeout: int


#: The ``pyproject.toml`` table a repo declares its own handlers in: ``[[tool.dev_lab.agent_hooks]]``.
DECLARED_TABLE: Final = 'agent_hooks'
_KEYS: Final = frozenset({'events', 'module', 'args', 'tools', 'may_block', 'once', 'timeout'})


class WireRefused(ValueError):
    """A repo-declared wire the dispatcher will not run, named with its cause and the table to fix."""


@contextlib.contextmanager
def import_root(root: Path) -> Iterator[None]:
    """*root* first on the import path for the block: where a repo-declared module is looked up and imported."""
    entry = str(root)
    sys.path.insert(0, entry)
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(entry)


def _strings(raw: Mapping[str, Any], key: str, where: str, *, required: bool = False) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        msg = f'{where}: {key} must be a list of non-empty strings, not {value!r}'
        raise WireRefused(msg)
    if required and not value:
        msg = f'{where}: {key} names no event, so the row would never run'
        raise WireRefused(msg)
    return tuple(value)


def _flag(raw: Mapping[str, Any], key: str, where: str) -> bool:
    value = raw.get(key, False)
    if not isinstance(value, bool):
        msg = f'{where}: {key} must be true or false, not {value!r}'
        raise WireRefused(msg)
    return value


def _wire(raw: object, where: str) -> Wire:
    if not isinstance(raw, dict):
        msg = f'{where}: a row is a table, not {raw!r}'
        raise WireRefused(msg)
    if unknown := sorted(set(raw) - _KEYS):
        msg = f'{where}: unknown key(s) {unknown}; the keys are {sorted(_KEYS)}'
        raise WireRefused(msg)
    module, timeout = raw.get('module'), raw.get('timeout', 30)
    if not isinstance(module, str) or not module or ' ' in module:
        msg = f'{where}: module must name one importable module, not {module!r}'
        raise WireRefused(msg)
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        msg = f'{where}: timeout must be a positive whole number of seconds, not {timeout!r}'
        raise WireRefused(msg)
    return Wire(
        _strings(raw, 'events', where, required=True),
        module,
        _strings(raw, 'args', where),
        tools=_strings(raw, 'tools', where),
        may_block=_flag(raw, 'may_block', where),
        once=_flag(raw, 'once', where),
        timeout=timeout,
    )


def _importable(module: str, root: Path) -> bool:
    with import_root(root):
        try:
            return importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            return False


def declared(root: Path) -> tuple[Wire, ...]:
    """The wires *root*'s ``pyproject.toml`` declares under ``[[tool.dev_lab.agent_hooks]]``; ``()`` when none.

    Raises:
        WireRefused: a row of the wrong shape, a module not importable from the repo's venv with *root* on the path,
            or a row whose name (module and args) repeats a family row or an earlier declared row.

    """
    manifest = root / 'pyproject.toml'
    if not manifest.is_file():
        return ()
    table = declared_table(tomllib.loads(manifest.read_text(encoding='utf-8')), DECLARED_TABLE, [])
    if not isinstance(table, list):
        msg = f'{manifest}: [tool.dev_lab.{DECLARED_TABLE}] is an array of tables: [[tool.dev_lab.{DECLARED_TABLE}]]'
        raise WireRefused(msg)
    family = {wire.name for wire in WIRING}
    out: list[Wire] = []
    for index, raw in enumerate(table, 1):
        where = f'{manifest}: [[tool.dev_lab.{DECLARED_TABLE}]] row {index}'
        wire = _wire(raw, where)
        if wire.name in family:
            msg = f'{where} ({wire.name}) duplicates a family row -- the family already wires it; delete the row'
            raise WireRefused(msg)
        if wire.name in {mine.name for mine in out}:
            msg = f'{where} ({wire.name}) is declared twice; keep one row and list every event on it'
            raise WireRefused(msg)
        if not _importable(wire.module, root):
            msg = f'{where}: {wire.module} is not importable from this venv with {root} on the path'
            raise WireRefused(msg)
        out.append(wire)
    return tuple(out)


def wiring(root: Path | None = None) -> tuple[Wire, ...]:
    """Every handler: :data:`WIRING`, then what *root* declares (:func:`declared`); the family's alone without one.

    Raises:
        WireRefused: *root*'s declaration is refused (:func:`declared`).

    """
    return WIRING if root is None else (*WIRING, *declared(root))


def events(wires: tuple[Wire, ...] = WIRING) -> tuple[str, ...]:
    """Every event *wires* serve, in first-declared order."""
    return tuple(dict.fromkeys(event for wire in wires for event in wire.events))


def rows(root: Path | None = None) -> tuple[Row, ...]:
    """THE RENDERED ROWS, derived: the engine, then one dispatcher row per event of :func:`wiring` (*root*).

    A row's matcher is the union of its handlers' tools -- none when any handler sees every call -- and its timeout
    the sum of its handlers' bounds.

    Raises:
        WireRefused: *root*'s declaration is refused (:func:`declared`).

    """
    every = wiring(root)
    out = [Row('PreToolUse', '|'.join(SHELL_TOOLS), HOOK_COMMAND, 30)]
    for event in events(every):
        wires = [wire for wire in every if event in wire.events]
        tools = tuple(dict.fromkeys(tool for wire in wires for tool in wire.tools))
        matcher = None if any(not wire.tools for wire in wires) else '|'.join(tools)
        out.append(Row(event, matcher, dispatch_command(event), sum(wire.timeout for wire in wires)))
    return tuple(out)
