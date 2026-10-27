"""AGENT-GUARD-IS-LIVE: is the deny registry a repo DECLARES actually ENFORCED in that repo?

THE SAME GAP :mod:`dev_lab.dev.hook_install` closes, one layer up and measured the same week.
There, a hook table is a DECLARATION and installing its shims a separate act on a separate
machine, with nothing linking the two -- and three repos declared a full set of hooks with ZERO
hooks on disk. Here the declaration is ``.claude/hooks/deny-rules.json``, rendered from the
shared registry by :func:`dev_lab.dev.hook_adoption.render`, and the separate act is installing
an ENGINE and pointing a ``PreToolUse`` matcher at it. MEASURED 2026-09-17: the registry existed, the
recipe existed, and the engine existed in exactly ONE repo of four. A rendered ``deny-rules.json`` in
any of the other three would have been an INERT DECLARATION THAT READS AS A GUARD.

THREE PARTS, AND ALL THREE MUST BE LIVE. Any one of them missing makes the other two decorative, and
each fails in its own way, so each is reported by name rather than collapsed into one boolean:

``engine``   ``.claude/hooks/deny-commands.js`` -- installed from :mod:`dev_lab.dev.agenthooks`
             and recognised by its stamp, so a drifted copy is a finding rather than a fork.
``rules``    ``.claude/hooks/deny-rules.json`` -- the repo's OWN rendered declaration. This module
             never writes it: which rules a repo can honestly ship is
             :mod:`dev_lab.dev.hook_adoption`'s question, answered from that repo's remedies, and
             answering it from here would ship rules whose exits do not exist.
``wiring``   the ``PreToolUse`` Bash matcher in ``.claude/settings.json`` that runs the one over the
             other. Unwired, the other two are two files nobody reads.

INSTALLING IS AN EXPLICIT REQUEST, and the default is read-only -- the posture
:mod:`dev_lab.dev.hook_install` argues for and for the same two reasons: a silent write into a
shared checkout is a mutation another party learns about by accident, and it would also make
``unguarded`` unobservable. The install NEVER clobbers: unrelated settings keys, unrelated matchers
and unrelated hooks in the Bash matcher are preserved, and an engine file that is somebody ELSE's
(no stamp) refuses rather than being overwritten.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.agenthooks import STAMP, engine_source
from dev_lab.dev.venvpath import running_interpreter

__all__ = [
    'ABSENT',
    'ENGINE_REL',
    'FOREIGN',
    'GUARDED',
    'HOOK_COMMAND',
    'INSTALLED',
    'LAUNCHER_REL',
    'NOTHING_DECLARED',
    'PART_NAMES',
    'RULES_REL',
    'SETTINGS_REL',
    'STALE',
    'UNGUARDED',
    'GuardReport',
    'PartReport',
    'engine_beside',
    'guard_installation',
    'install_guard',
    'launcher_source',
    'report_guard',
    'wire_settings',
]

#: The verdict for ONE part. The middle two are the point: a file that is present but stale enforces
#: yesterday's registry while looking current, and a file somebody hand-wrote must not be silently
#: overwritten by an install.
INSTALLED: Final = 'installed'
ABSENT: Final = 'declared-but-absent'
STALE: Final = 'present-but-stale'
FOREIGN: Final = 'present-but-not-lab-commons'

#: The three-valued TOP answer. ``NOTHING_DECLARED`` is not a pass and not a failure -- it is the
#: absence of a question, and folding it into ``GUARDED`` would let a repo that has never adopted the
#: registry report exactly as reassuringly as one that is fully wired.
GUARDED: Final = 'guarded'
UNGUARDED: Final = 'unguarded'
NOTHING_DECLARED: Final = 'nothing-declared'

#: Repo-relative locations. RELATIVE on purpose: ``.claude/settings.json`` is committed and read on
#: other boxes, so an absolute ``site-packages`` path in the hook command would be true on exactly
#: one machine. These are the spellings consumer-a already uses, so the one repo that was
#: guarded before this module existed verifies as installed rather than as a variant.
ENGINE_REL: Final = '.claude/hooks/deny-commands.js'
RULES_REL: Final = '.claude/hooks/deny-rules.json'
SETTINGS_REL: Final = '.claude/settings.json'

#: THE ONE DOOR a hook reaches this checkout's interpreter through: a node launcher that resolves the venv
#: per platform (and the main checkout's from a linked worktree). A hook spelling ``.venv`` inline drifts
#: from it -- motronics pins that (``test_no_hook_spells_its_own_interpreter``). A repo's own launcher at
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

_LAUNCHER_SHIPPED: Final = Path(__file__).resolve().with_name('agent_launcher.js')


def launcher_source() -> str:
    """The shipped launcher's text."""
    return _LAUNCHER_SHIPPED.read_text(encoding='utf-8')


#: The STRAY-FILE-REFUSED census (:mod:`dev_lab.dev.codeplace` ``stray``), through :data:`LAUNCHER_REL`. A
#: checkout with no venv is NOT blocked (decision 7, 2026-10-22): the launcher exits 0 without one.
STRAY_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.codeplace stray'

#: AGENT-RUNS-ITS-OWN-COMMANDS (:mod:`dev_lab.dev.handback`): a final message handing the user a runnable
#: command blocks the stop, for the main session and for every subagent.
HANDBACK_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.handback'

#: RECLAIM RUNS IN THE WORKFLOW (:mod:`dev_lab.dev.reclaimrun`, ruling 2026-10-27): every session start in a
#: MAIN checkout detaches a bounded, locked reclaim of landed worktrees and their branches, and returns at once.
RECLAIM_COMMAND: Final = f'node "$CLAUDE_PROJECT_DIR/{LAUNCHER_REL}" -m dev_lab.dev.reclaimrun --session-start'


@dataclass(frozen=True, slots=True)
class Wire:
    """One hook the guard owns: its event, its command, the text marking a hook OURS, and its home.

    ``on_shells`` homes it on the matcher naming every shell tool; otherwise on a matcher-less entry.
    """

    event: str
    command: str
    marker: str
    on_shells: bool


#: THE WIRING, ONE TABLE: what :func:`wire_settings` writes is what :func:`guard_installation` reads.
#: The engine before every shell call; the STRAY-FILE-REFUSED census after every one, and at stop; the
#: hand-back check at every stop, the main session's and each subagent's; the background reclaim at session start.
WIRING: Final = (
    Wire('PreToolUse', HOOK_COMMAND, Path(ENGINE_REL).name, on_shells=True),
    Wire('PostToolUse', STRAY_COMMAND, 'dev_lab.dev.codeplace stray', on_shells=True),
    Wire('Stop', STRAY_COMMAND, 'dev_lab.dev.codeplace stray', on_shells=False),
    Wire('Stop', HANDBACK_COMMAND, 'dev_lab.dev.handback', on_shells=False),
    Wire('SubagentStop', HANDBACK_COMMAND, 'dev_lab.dev.handback', on_shells=False),
    Wire('SessionStart', RECLAIM_COMMAND, 'dev_lab.dev.reclaimrun', on_shells=False),
)

#: The parts, in the order a reader should fix them: an engine with no rules refuses nothing, and
#: rules with no wiring are read by nobody.
PART_NAMES: Final = ('engine', 'rules', 'wiring')


def engine_beside(rules: Path) -> Path:
    """The engine that judges *rules*: its SIBLING, because :data:`ENGINE_REL` and :data:`RULES_REL` are.

    THE ONE PLACE THAT LAYOUT FACT IS SPELLED, so a body that is handed a rules file can name the
    engine which will actually read it without being handed a root as well, and without any body
    defaulting to the wheel's copy. Derived from the CALLER'S OWN argument rather than guessed: the
    family's no-default doctrine is about one repo's answer being handed silently to another, and
    "the engine beside the rules you named" is not an answer this module supplied.

    A path is returned whether or not anything is there. Whether it exists is
    :func:`dev_lab.dev.agenthooks.run_engine`'s refusal to make, in one place, rather than a
    check every caller repeats slightly differently.
    """
    return rules.parent / Path(ENGINE_REL).name


#: The tools that issue a command line. A rule about a COMMAND can only be enforced where a command
#: is issued, and BOTH shell tools issue one: until 2026-10-08 the matcher named Bash alone, and every
#: denied shape ran unjudged through the PowerShell tool.
SHELL_TOOLS: Final = ('Bash', 'PowerShell')

#: The matcher the guard's hook lives on -- every shell tool, and nothing else.
_MATCHER: Final = '|'.join(SHELL_TOOLS)


def _tools(entry: object) -> frozenset[str]:
    """The shell tools a ``PreToolUse`` entry's matcher names (an alternation of tool names)."""
    if not isinstance(entry, dict):
        return frozenset()
    return frozenset(str(entry.get('matcher', '')).split('|')) & frozenset(SHELL_TOOLS)


def _is_ours(hook: object) -> bool:
    return isinstance(hook, dict) and Path(ENGINE_REL).name in str(hook.get('command', ''))


@dataclass(frozen=True, slots=True)
class PartReport:
    """One part of the guard: where it should be, what is there, and what that means."""

    part: str
    status: str
    detail: str
    path: Path


@dataclass(frozen=True, slots=True)
class GuardReport:
    """Every part of one repository's agent guard, plus the three-valued top answer."""

    repo: Path
    parts: tuple[PartReport, ...]

    @property
    def by_part(self) -> dict[str, PartReport]:
        """The parts by name, so a caller asks a question instead of indexing a tuple."""
        return {part.part: part for part in self.parts}

    @property
    def verdict(self) -> str:
        """``GUARDED`` only when all three parts are live; ``NOTHING_DECLARED`` when none exist."""
        statuses = {part.part: part.status for part in self.parts}
        if all(status == ABSENT for status in statuses.values()):
            return NOTHING_DECLARED
        return GUARDED if all(status == INSTALLED for status in statuses.values()) else UNGUARDED

    @property
    def failing(self) -> tuple[PartReport, ...]:
        """The parts that are absent, stale, or somebody else's."""
        return tuple(part for part in self.parts if part.status != INSTALLED)


def _stamp_block(text: str) -> tuple[str, ...]:
    """The contiguous run of comment lines carrying :data:`STAMP`, as lines."""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if STAMP in line:
            end = index
            while end < len(lines) and lines[end].lstrip().startswith('//'):
                end += 1
            return tuple(lines[index:end])
    return ()


def _without_stamp(text: str) -> str:
    """*text* with its provenance block removed.

    How an UNSTAMPED copy is recognised as the same engine. It is the difference between "somebody
    wrote their own engine here" and "this copy predates the shipped payload", and those two need
    different remedies.
    """
    block = _stamp_block(text)
    return ''.join(line for line in text.splitlines(keepends=True) if line not in block)


def _inspect_engine(path: Path) -> tuple[str, str]:
    if not path.exists():
        return ABSENT, 'no engine at this path -- every rendered rule in this repo refuses nothing'
    text = path.read_text(encoding='utf-8')
    shipped = engine_source()
    if text == shipped:
        return INSTALLED, f'the shipped engine, {len(text.splitlines())} lines'
    if STAMP not in text:
        if _without_stamp(text) == _without_stamp(shipped):
            return FOREIGN, 'unstamped, but identical to the shipped engine apart from its provenance block'
        return FOREIGN, 'a hook engine is here that lab-commons did not ship; installing would overwrite it'
    return STALE, 'stamped by lab-commons but its bytes differ from the shipped engine -- re-install to refresh'


def _inspect_rules(path: Path) -> tuple[str, str]:
    if not path.exists():
        return ABSENT, f'no {RULES_REL} -- render one with dev_lab.dev.hook_adoption.render'
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        return STALE, f'unreadable JSON ({error.msg}); the engine FAILS OPEN on it, so nothing is refused'
    if not isinstance(rows, list) or not rows:
        return STALE, 'not a non-empty JSON array; the engine ignores it, so nothing is refused'
    named = ', '.join(str(row.get('name', '?')) for row in rows if isinstance(row, dict))
    return INSTALLED, f'{len(rows)} rule(s): {named}'


def _hook_entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every ``PreToolUse`` command hook on a matcher naming EVERY shell tool, as the raw dicts.

    A hook on a matcher missing one of :data:`SHELL_TOOLS` is not counted: it leaves that tool
    unjudged, so the wiring reads as stale rather than installed.
    """
    out: list[dict[str, Any]] = []
    for entry in settings.get('hooks', {}).get('PreToolUse', []) or []:
        if _tools(entry) != frozenset(SHELL_TOOLS):
            continue
        out += [hook for hook in entry.get('hooks', []) or [] if isinstance(hook, dict)]
    return out


def _no_engine_hook(settings: dict[str, Any]) -> tuple[str, str]:
    """No full-shell hook runs the engine: STALE when one runs it on a partial matcher, else ABSENT."""
    partial = [
        str(entry.get('matcher'))
        for entry in settings.get('hooks', {}).get('PreToolUse', []) or []
        if _tools(entry) and any(_is_ours(hook) for hook in entry.get('hooks', []) or [])
    ]
    if partial:
        return STALE, f'the engine runs on matcher {partial[0]!r}, which leaves a shell tool unjudged'
    return ABSENT, f'no PreToolUse {_MATCHER} hook runs {Path(ENGINE_REL).name}'


def _inspect_wiring(path: Path) -> tuple[str, str]:
    if not path.exists():
        return ABSENT, f'no {SETTINGS_REL} -- nothing runs the engine, whatever is installed beside it'
    try:
        settings = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        return STALE, f'unreadable JSON ({error.msg}) -- the tool reads no hooks out of it'
    commands = [str(hook.get('command', '')) for hook in _hook_entries(settings)]
    ours = [command for command in commands if Path(ENGINE_REL).name in command]
    if not ours:
        return _no_engine_hook(settings)
    if HOOK_COMMAND not in ours:
        return STALE, f'runs the engine with other arguments: {ours[0]!r}, not {HOOK_COMMAND!r}'
    unwired = _unwired(settings)
    if unwired:
        return STALE, f'the stray census is not wired on {", ".join(unwired)} -- re-install to upgrade'
    return INSTALLED, f'PreToolUse {_MATCHER}: {HOOK_COMMAND}'


def guard_installation(repo: Path) -> GuardReport:
    """Answer, for *repo*, whether its agent guard is LIVE -- engine, rules and wiring, by name."""
    parts = (
        PartReport('engine', *_inspect_engine(repo / ENGINE_REL), path=repo / ENGINE_REL),
        PartReport('rules', *_inspect_rules(repo / RULES_REL), path=repo / RULES_REL),
        PartReport('wiring', *_inspect_wiring(repo / SETTINGS_REL), path=repo / SETTINGS_REL),
    )
    return GuardReport(repo=repo, parts=parts)


def wire_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """*settings* with the guard's ``PreToolUse`` shell hook and the stray census present, and NOTHING ELSE MOVED.

    Pure over its argument -- the input is not mutated -- so the suite drives THIS function over a
    planted foreign settings file rather than re-deriving what "did not clobber" means.

    Our hook lives on a matcher naming EVERY shell tool. A copy of it on a matcher missing one (the
    pre-2026-10-08 ``Bash`` wiring) is MOVED rather than widened in place: widening that matcher
    would also hand every OTHER hook on it a tool its author never meant it to see. Other hooks on a
    full shell matcher are kept, and our own hook there is replaced in place.
    """
    out = json.loads(json.dumps(settings))  # a deep copy through the same encoder that writes it
    for wire in WIRING:
        _wire(out.setdefault('hooks', {}).setdefault(wire.event, []), wire)
    return out


def _mine(hook: object, wire: Wire) -> bool:
    return isinstance(hook, dict) and wire.marker in str(hook.get('command', ''))


def _home(entry: object, wire: Wire) -> bool:
    """Whether *entry* is where *wire* lives: the full shell matcher, or any entry for a matcher-less wire."""
    return isinstance(entry, dict) and (_tools(entry) == frozenset(SHELL_TOOLS) if wire.on_shells else True)


def _wire(entries: list[Any], wire: Wire) -> None:
    """*wire* present exactly once in *entries*: moved off a partial shell matcher, else replaced in place."""
    hook = {'type': 'command', 'command': wire.command}
    if wire.on_shells:
        stripped = [
            e for e in entries if _tools(e) and not _home(e, wire) and any(_mine(h, wire) for h in e.get('hooks') or [])
        ]
        for entry in stripped:
            entry['hooks'] = [h for h in entry['hooks'] if not _mine(h, wire)]
        entries[:] = [e for e in entries if not any(e is s for s in stripped) or e['hooks']]
    homes = [e for e in entries if _home(e, wire)]
    for entry in homes:
        found = [i for i, h in enumerate(entry.get('hooks', []) or []) if _mine(h, wire)]
        if found:
            entry['hooks'][found[0]] = hook
            return
    if wire.on_shells and homes:
        homes[0].setdefault('hooks', []).append(hook)
    else:
        entries.append({'matcher': _MATCHER, 'hooks': [hook]} if wire.on_shells else {'hooks': [hook]})


def _unwired(settings: dict[str, Any]) -> list[str]:
    """The events of :data:`WIRING` past the engine whose exact command is not at its home."""
    return [
        wire.event
        for wire in WIRING[1:]
        if not any(
            isinstance(h, dict) and h.get('command') == wire.command
            for e in settings.get('hooks', {}).get(wire.event, []) or []
            if _home(e, wire)
            for h in e.get('hooks', []) or []
        )
    ]


def install_guard(repo: Path, *, force: bool = False) -> tuple[str, ...]:
    """Install the engine into *repo* and wire it, returning what was DONE, one line per action.

    THE RULES FILE IS NOT WRITTEN HERE, and that is the design rather than an omission: which rules a
    repo can honestly ship depends on the remedies that repo offers, which only
    :mod:`dev_lab.dev.hook_adoption` can answer. Shipping a default set from here would install
    rules whose exits do not exist in the tree reading them -- the sealed-road failure the registry
    was built to prevent.

    Raises:
        FileExistsError: when an engine file is present that lab-commons did not ship. Overwriting
            somebody's hand-written hook is not an install, it is a deletion; pass *force* to mean it.

    """
    engine = repo / ENGINE_REL
    status, detail = _inspect_engine(engine)
    actions: list[str] = []
    if status == FOREIGN and not force:
        msg = f'{engine}: {detail}. Re-run with force=True if replacing it is what you mean.'
        raise FileExistsError(msg)
    if status == INSTALLED:
        actions.append(f'engine already current: {engine}')
    else:
        engine.parent.mkdir(parents=True, exist_ok=True)
        engine.write_text(engine_source(), encoding='utf-8')
        actions.append(f'engine {"replaced" if status != ABSENT else "installed"}: {engine}')

    launcher = repo / LAUNCHER_REL
    if launcher.exists():
        actions.append(f'launcher already present, kept: {launcher}')
    else:
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_text(launcher_source(), encoding='utf-8')
        actions.append(f'launcher installed: {launcher}')

    settings_path = repo / SETTINGS_REL
    before: dict[str, Any] = {}
    if settings_path.exists():
        before = json.loads(settings_path.read_text(encoding='utf-8'))
    after = wire_settings(before)
    if after == before:
        actions.append(f'wiring already present: {settings_path}')
    else:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(after, indent=2) + '\n', encoding='utf-8')
        actions.append(f'wiring {"updated" if before else "written"}: {settings_path}')
    return tuple(actions)


def report_guard(argv: list[str] | None = None) -> int:
    """CLI. Exit 0 = the guard is live, 1 = it is not, 2 = this repo has not adopted it at all.

    THREE EXIT CODES BECAUSE THERE ARE THREE ANSWERS, and the refusal NAMES ITS REMEDY -- the
    unguarded report ends with the exact command that installs what is missing.
    """
    parser = argparse.ArgumentParser(description="Is this repository's agent guard actually live?")
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    parser.add_argument('--install', action='store_true', help='install and wire the engine (an EXPLICIT request)')
    parser.add_argument(
        '--force', action='store_true', help='with --install: replace an engine lab-commons did not ship'
    )
    args = parser.parse_args(argv)
    root = args.repo.resolve()

    if args.install:
        for action in install_guard(root, force=args.force):
            emit(f'[agent-guard] {action}')

    report = guard_installation(root)
    for part in report.parts:
        emit(f'  {part.part:<8} {part.status:<28} {part.detail}')
    if report.verdict == NOTHING_DECLARED:
        emit(f'[agent-guard] NOTHING DECLARED -- no agent guard in {report.repo} at all')
        return 2
    if report.verdict == GUARDED:
        emit('[agent-guard] OK -- engine, rules and wiring are all live.')
        return 0
    emit(
        f'[agent-guard] UNGUARDED -- {len(report.failing)} of {len(report.parts)} part(s) are not the '
        f'installed guard: {", ".join(part.part for part in report.failing)}. An ABSENT or unreadable part '
        f'refuses nothing, and every agent command so far went through it; a FOREIGN one may well refuse '
        f'things, but it is enforcing a file nobody in this family can vouch for.\n'
        f'  Install with:  {running_interpreter()} -m dev_lab.dev.agent_guard --install --repo {report.repo}'
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(report_guard())
