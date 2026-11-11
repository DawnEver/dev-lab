"""The hook WIRING :mod:`dev_lab.dev.agent_guard` installs and inspects, as data: paths, commands, one table.

Split from the install/inspection half so the table a hook module is wired by reads as one page; every
hook module that pins its own row imports it from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = [
    'AUTOMODE_COMMAND',
    'ENGINE_REL',
    'HANDBACK_COMMAND',
    'HOOK_COMMAND',
    'JOURNALDOOR_COMMAND',
    'LAUNCHER_REL',
    'PRESSURE_COMMAND',
    'PUSHSTOP_COMMAND',
    'PUSHWATCH_COMMAND',
    'RECLAIM_COMMAND',
    'RETIRED_WIRING',
    'RULES_REL',
    'SESSIONPRS_COMMAND',
    'SETTINGS_REL',
    'SHELL_TOOLS',
    'STRAY_COMMAND',
    'SWEEP_COMMAND',
    'VENVFOLLOW_COMMAND',
    'WIRING',
    'Wire',
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
#: So the line is a POSIX wrapper: no engine file, or any engine exit but 0, exits 2 (blocking) naming why.
HOOK_COMMAND: Final = (
    f'e="$CLAUDE_PROJECT_DIR/{ENGINE_REL}"; '
    '[ -f "$e" ] || { echo "agent-guard: no engine at $e -- refused (fail closed); '
    f're-install: node $CLAUDE_PROJECT_DIR/{LAUNCHER_REL} -m dev_lab.dev.hook_install --install" >&2; exit 2; }}; '
    f'node "$e" "$CLAUDE_PROJECT_DIR/{RULES_REL}" || '
    '{ echo "agent-guard: the engine exited $? -- refused (fail closed)" >&2; exit 2; }'
)


#: The tools that issue a command line. A rule about a COMMAND can only be enforced where a command
#: is issued, and BOTH shell tools issue one: until 2026-10-08 the matcher named Bash alone, and every
#: denied shape ran unjudged through the PowerShell tool.
SHELL_TOOLS: Final = ('Bash', 'PowerShell')


#: The STRAY-FILE-REFUSED census (:mod:`dev_lab.dev.codeplace` ``stray``), through :data:`LAUNCHER_REL`. A
#: checkout with no venv is NOT blocked (decision 7, 2026-10-22): the launcher exits 0 without one.
STRAY_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.codeplace stray'

#: AGENT-RUNS-ITS-OWN-COMMANDS (:mod:`dev_lab.dev.handback`): a final message handing the user a runnable
#: command blocks the stop, for the main session and for every subagent.
HANDBACK_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.handback'

#: TRACKED-CITES-NO-EPHEMERAL at the door (:mod:`dev_lab.dev.journaldoor`, dev-lab#419): a task-journal append
#: citing an ignored path is refused before it is written.
JOURNALDOOR_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.journaldoor'

#: PUSHED-HEAD-IS-WATCHED (:mod:`dev_lab.dev.pushwatch`): after a shell call that pushed, ONE advisory line when
#: no live ``forge watch <sha>`` watches the pushed head -- never a block.
PUSHWATCH_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.pushwatch'

#: SESSION-HEARS-ITS-PRS (:mod:`dev_lab.dev.sessionprs`, ruling 2026-11-11): after a shell call that pushed or ran
#: ``forge pr create``, the PR is recorded as the session's, in any repository; an opened PR names the watch to arm.
SESSIONPRS_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.sessionprs'

#: PUSHED-HEAD-IS-WATCHED, the ``Stop`` half (:mod:`dev_lab.dev.pushstop`, ruling 2026-11-04): a turn does not end
#: while a head the session pushed is pending with no live watcher, or red (refused once).
PUSHSTOP_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.pushstop'

#: LANDED-BRANCHES-SWEPT (:mod:`dev_lab.dev.branchprune`, ruling 2026-10-29): after a shell call that pushed
#: integration, a detached ``sweep --local`` deletes every branch and clean worktree integration now contains.
SWEEP_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.branchprune post-push'

#: RECLAIM RUNS IN THE WORKFLOW (:mod:`dev_lab.dev.reclaimrun`, ruling 2026-10-27): every session start in a
#: MAIN checkout detaches a bounded, locked reclaim of landed worktrees and their branches, and returns at once.
RECLAIM_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.reclaimrun --session-start'

#: VENV-FOLLOWS-THE-LOCK (:mod:`dev_lab.dev.venvfollow`, ruling 2026-11-04): every session start whose checkout's
#: lock moved since its venv was stamped detaches a re-bootstrap, and returns at once.
VENVFOLLOW_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.venvfollow --session-start'

#: THE CLASSIFIER PROSE FOLLOWS THE CHECKOUT (:mod:`dev_lab.dev.automode`, 2026-11-09): every session start renders
#: the classifier's intents file from the policy table and the repo's own intents, so a door added to the table
#: reaches the classifier on the next session, not on the next dependency sync (a ten-day-old render withheld one).
AUTOMODE_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.automode session-start'

#: A PRESSED HOST TELLS ITS AGENTS (:mod:`dev_lab.dev.hostalarm`, ruling D54): the host's disk/memory/CPU alarms as
#: additional context after a shell call and on each prompt, once per alarm per session per 30 minutes.
PRESSURE_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.hostalarm hook'


@dataclass(frozen=True, slots=True)
class Wire:
    """One hook the guard owns: its event, its command, the text marking a hook OURS, and its home.

    ``on_shells`` homes it on the matcher naming every shell tool; otherwise on a matcher-less entry.
    """

    event: str
    command: str
    marker: str
    on_shells: bool


#: THE WIRING, ONE TABLE: what :func:`dev_lab.dev.agent_guard.wire_settings` writes is what
#: :func:`dev_lab.dev.agent_guard.guard_installation` reads.
#: The engine and the journal door before every shell call; the pushed-head reminder, the landed sweep and the
#: host-pressure reminder after every one (the reminder on each prompt too); the STRAY-FILE-REFUSED census ONCE, at
#: stop -- a stray is the state a turn leaves, the PreToolUse refusals stop a misplaced write as it is made, and a
#: census after every shell call repeated the same block (2026-11-03 audit); the hand-back check at every stop, the
#: main session's and each subagent's; the pushed-head gate at the main session's stop; the background reclaim at
#: session start.
WIRING: Final = (
    Wire('PreToolUse', HOOK_COMMAND, Path(ENGINE_REL).name, on_shells=True),
    Wire('PreToolUse', JOURNALDOOR_COMMAND, 'dev_lab.dev.journaldoor', on_shells=True),
    Wire('PostToolUse', PUSHWATCH_COMMAND, 'dev_lab.dev.pushwatch', on_shells=True),
    Wire('PostToolUse', SESSIONPRS_COMMAND, 'dev_lab.dev.sessionprs', on_shells=True),
    Wire('PostToolUse', SWEEP_COMMAND, 'dev_lab.dev.branchprune post-push', on_shells=True),
    Wire('PostToolUse', PRESSURE_COMMAND, 'dev_lab.dev.hostalarm', on_shells=True),
    Wire('UserPromptSubmit', PRESSURE_COMMAND, 'dev_lab.dev.hostalarm', on_shells=False),
    Wire('Stop', STRAY_COMMAND, 'dev_lab.dev.codeplace stray', on_shells=False),
    Wire('Stop', HANDBACK_COMMAND, 'dev_lab.dev.handback', on_shells=False),
    Wire('Stop', PUSHSTOP_COMMAND, 'dev_lab.dev.pushstop', on_shells=False),
    Wire('SubagentStop', HANDBACK_COMMAND, 'dev_lab.dev.handback', on_shells=False),
    Wire('SessionStart', RECLAIM_COMMAND, 'dev_lab.dev.reclaimrun', on_shells=False),
    Wire('SessionStart', VENVFOLLOW_COMMAND, 'dev_lab.dev.venvfollow', on_shells=False),
    Wire('SessionStart', AUTOMODE_COMMAND, 'dev_lab.dev.automode session-start', on_shells=False),
)

#: Wires the family once installed and no longer does, as ``(event, marker)``: a re-install removes them, so an old
#: settings file is not left running a hook the wiring retired (no-backward-compatibility).
RETIRED_WIRING: Final = (('PostToolUse', 'dev_lab.dev.codeplace stray'),)
