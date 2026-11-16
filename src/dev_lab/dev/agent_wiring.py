"""The hook WIRING, as data: the engine's paths and command, and the ONE table of handlers per event.

:mod:`dev_lab.dev.agent_guard` renders :func:`rows` into settings; :mod:`dev_lab.dev.hookdispatch` reads
:data:`WIRING` at run time. Both read the same installed table, so a settings row never names a handler the
interpreter running it lacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

__all__ = [
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
    'dispatch_command',
    'events',
    'rows',
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

#: THE WIRING, ONE TABLE. Before every shell call: the journal door (TRACKED-CITES-NO-EPHEMERAL, dev-lab#419); before
#: every write: the codeplace write hook (a report under output/, a write-prone root, a consent file refused; a
#: misplaced code file hinted). After every shell call, succeeded or failed: the wall ledger's foreign-denial reader
#: (WALLS-ARE-RECORDED). Each prompt: the host-pressure reminder (D54) and the PR inbox -- the ONE machine PR watcher
#: (SESSION-HEARS-ITS-PRS); the task binding is rem's own prompt hook, never a row here. Every stop, the main
#: session's and each subagent's: the hand-back check and the wall ledger's stop; the main session's adds the stray
#: census, the scratch census, the unfilled install home and the shell reaper. Session start: the ONE reclaim, the
#: reaper, the venv follower, the forge-token notice, the scratch baseline, the classifier render and the PR watcher.
WIRING: Final = (
    Wire(('PreToolUse',), 'dev_lab.dev.journaldoor', tools=SHELL_TOOLS, may_block=True),
    Wire(('PreToolUse',), 'dev_lab.dev.codeplace', tools=WRITE_TOOLS, may_block=True),
    Wire(('PostToolUse', 'PostToolUseFailure'), 'dev_lab.dev.walls', ('post-tool',), tools=SHELL_TOOLS),
    Wire(('UserPromptSubmit',), 'dev_lab.dev.hostalarm', ('hook',)),
    Wire(('UserPromptSubmit',), 'dev_lab.dev.prwatcher', ('inbox',)),
    Wire(('Stop',), 'dev_lab.dev.codeplace', ('stray',), may_block=True, timeout=60),
    Wire(_STOPS, 'dev_lab.dev.handback', may_block=True, timeout=60),
    Wire(('Stop',), 'dev_lab.dev.scratch', ('stop',), may_block=True, timeout=60),
    Wire(('Stop',), 'dev_lab.dev.devhost', ('stop',), may_block=True, timeout=60),
    Wire(_STOPS, 'dev_lab.dev.walls', ('stop',), may_block=True, timeout=60),
    Wire(('Stop', 'SessionStart'), 'dev_lab.dev.shellreaper', ('--hook',), timeout=60),
    Wire(('SessionStart',), 'dev_lab.dev.reclaimrun', ('--session-start',), once=True, timeout=120),
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


def events() -> tuple[str, ...]:
    """Every event :data:`WIRING` serves, in first-declared order."""
    return tuple(dict.fromkeys(event for wire in WIRING for event in wire.events))


def rows() -> tuple[Row, ...]:
    """THE RENDERED ROWS, derived: the engine, then one dispatcher row per event of :data:`WIRING`.

    A row's matcher is the union of its handlers' tools -- none when any handler sees every call -- and its timeout
    the sum of its handlers' bounds.
    """
    out = [Row('PreToolUse', '|'.join(SHELL_TOOLS), HOOK_COMMAND, 30)]
    for event in events():
        wires = [wire for wire in WIRING if event in wire.events]
        tools = tuple(dict.fromkeys(tool for wire in wires for tool in wire.tools))
        matcher = None if any(not wire.tools for wire in wires) else '|'.join(tools)
        out.append(Row(event, matcher, dispatch_command(event), sum(wire.timeout for wire in wires)))
    return tuple(out)
