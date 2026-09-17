"""AGENT-GUARD-IS-LIVE: is the deny registry a repo DECLARES actually ENFORCED in that repo?

THE SAME GAP :mod:`lab_commons.dev.hook_install` closes, one layer up and measured the same week.
There, a ``.pre-commit-config.yaml`` was a DECLARATION and ``pre-commit install`` a separate act on a
separate machine, with nothing linking the two -- and three repos declared a full configuration with
ZERO hooks on disk. Here the declaration is ``.claude/hooks/deny-rules.json``, rendered from the
shared registry by :func:`lab_commons.dev.hook_adoption.render`, and the separate act is installing
an ENGINE and pointing a ``PreToolUse`` matcher at it. MEASURED 2026-09-17: the registry existed, the
recipe existed, and the engine existed in exactly ONE repo of four. A rendered ``deny-rules.json`` in
any of the other three would have been an INERT DECLARATION THAT READS AS A GUARD.

THREE PARTS, AND ALL THREE MUST BE LIVE. Any one of them missing makes the other two decorative, and
each fails in its own way, so each is reported by name rather than collapsed into one boolean:

``engine``   ``.claude/hooks/deny-commands.js`` -- installed from :mod:`lab_commons.dev.agenthooks`
             and recognised by its stamp, so a drifted copy is a finding rather than a fork.
``rules``    ``.claude/hooks/deny-rules.json`` -- the repo's OWN rendered declaration. This module
             never writes it: which rules a repo can honestly ship is
             :mod:`lab_commons.dev.hook_adoption`'s question, answered from that repo's remedies, and
             answering it from here would ship rules whose exits do not exist.
``wiring``   the ``PreToolUse`` Bash matcher in ``.claude/settings.json`` that runs the one over the
             other. Unwired, the other two are two files nobody reads.

INSTALLING IS AN EXPLICIT REQUEST, and the default is read-only -- the posture
:mod:`lab_commons.dev.hook_install` argues for and for the same two reasons: a silent write into a
shared checkout is a mutation another party learns about by accident, and it would also make
``unguarded`` unobservable. The install NEVER clobbers: unrelated settings keys, unrelated matchers
and unrelated hooks in the Bash matcher are preserved, and an engine file that is somebody ELSE's
(no stamp) refuses rather than being overwritten.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from lab_commons.dev.agenthooks import STAMP, engine_source

__all__ = [
    'ABSENT',
    'ENGINE_REL',
    'FOREIGN',
    'GUARDED',
    'HOOK_COMMAND',
    'INSTALLED',
    'NOTHING_DECLARED',
    'PART_NAMES',
    'RULES_REL',
    'SETTINGS_REL',
    'STALE',
    'UNGUARDED',
    'GuardReport',
    'PartReport',
    'guard_installation',
    'install_guard',
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
#: one machine. These are the spellings motronics-studio already uses, so the one repo that was
#: guarded before this module existed verifies as installed rather than as a variant.
ENGINE_REL: Final = '.claude/hooks/deny-commands.js'
RULES_REL: Final = '.claude/hooks/deny-rules.json'
SETTINGS_REL: Final = '.claude/settings.json'

#: The hook command line, DERIVED from the two paths above rather than spelled twice -- the lesson
#: :func:`lab_commons.dev.hook_install.install_command` records: a restatement of a path is a place
#: for the real one to move away from.
HOOK_COMMAND: Final = f'node {ENGINE_REL} {RULES_REL}'

#: The parts, in the order a reader should fix them: an engine with no rules refuses nothing, and
#: rules with no wiring are read by nobody.
PART_NAMES: Final = ('engine', 'rules', 'wiring')

#: The matcher the tool uses to select Bash tool calls. A rule about a COMMAND can only be enforced
#: where a command is issued.
_MATCHER: Final = 'Bash'


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
        return ABSENT, f'no {RULES_REL} -- render one with lab_commons.dev.hook_adoption.render'
    try:
        rows = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        return STALE, f'unreadable JSON ({error.msg}); the engine FAILS OPEN on it, so nothing is refused'
    if not isinstance(rows, list) or not rows:
        return STALE, 'not a non-empty JSON array; the engine ignores it, so nothing is refused'
    named = ', '.join(str(row.get('name', '?')) for row in rows if isinstance(row, dict))
    return INSTALLED, f'{len(rows)} rule(s): {named}'


def _hook_entries(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Every ``PreToolUse`` command hook attached to the Bash matcher, as the raw dicts."""
    out: list[dict[str, Any]] = []
    for entry in settings.get('hooks', {}).get('PreToolUse', []) or []:
        if not isinstance(entry, dict) or _MATCHER not in str(entry.get('matcher', '')):
            continue
        out += [hook for hook in entry.get('hooks', []) or [] if isinstance(hook, dict)]
    return out


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
        return ABSENT, f'no PreToolUse {_MATCHER} hook runs {Path(ENGINE_REL).name}'
    if HOOK_COMMAND in ours:
        return INSTALLED, f'PreToolUse {_MATCHER}: {HOOK_COMMAND}'
    return STALE, f'runs the engine with other arguments: {ours[0]!r}, not {HOOK_COMMAND!r}'


def guard_installation(repo: Path) -> GuardReport:
    """Answer, for *repo*, whether its agent guard is LIVE -- engine, rules and wiring, by name."""
    parts = (
        PartReport('engine', *_inspect_engine(repo / ENGINE_REL), path=repo / ENGINE_REL),
        PartReport('rules', *_inspect_rules(repo / RULES_REL), path=repo / RULES_REL),
        PartReport('wiring', *_inspect_wiring(repo / SETTINGS_REL), path=repo / SETTINGS_REL),
    )
    return GuardReport(repo=repo, parts=parts)


def wire_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """*settings* with the guard's ``PreToolUse`` Bash hook present, and NOTHING ELSE MOVED.

    Pure over its argument -- the input is not mutated -- so the suite drives THIS function over a
    planted foreign settings file rather than re-deriving what "did not clobber" means.

    Three cases, and the middle one is the one a naive writer gets wrong: no hooks at all (add), a
    Bash matcher that already carries OTHER hooks (append to it, keeping them), and our own hook
    already present under different arguments (replace that one hook, in place).
    """
    out = json.loads(json.dumps(settings))  # a deep copy through the same encoder that writes it
    hooks = out.setdefault('hooks', {})
    pre = hooks.setdefault('PreToolUse', [])
    ours = {'type': 'command', 'command': HOOK_COMMAND}
    for entry in pre:
        if not isinstance(entry, dict) or _MATCHER not in str(entry.get('matcher', '')):
            continue
        commands = entry.setdefault('hooks', [])
        for index, hook in enumerate(commands):
            if isinstance(hook, dict) and Path(ENGINE_REL).name in str(hook.get('command', '')):
                commands[index] = ours
                return out
        commands.append(ours)
        return out
    pre.append({'matcher': _MATCHER, 'hooks': [ours]})
    return out


def install_guard(repo: Path, *, force: bool = False) -> tuple[str, ...]:
    """Install the engine into *repo* and wire it, returning what was DONE, one line per action.

    THE RULES FILE IS NOT WRITTEN HERE, and that is the design rather than an omission: which rules a
    repo can honestly ship depends on the remedies that repo offers, which only
    :mod:`lab_commons.dev.hook_adoption` can answer. Shipping a default set from here would install
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
            sys.stdout.write(f'[agent-guard] {action}\n')

    report = guard_installation(root)
    for part in report.parts:
        sys.stdout.write(f'  {part.part:<8} {part.status:<28} {part.detail}\n')
    if report.verdict == NOTHING_DECLARED:
        sys.stdout.write(f'[agent-guard] NOTHING DECLARED -- no agent guard in {report.repo} at all\n')
        return 2
    if report.verdict == GUARDED:
        sys.stdout.write('[agent-guard] OK -- engine, rules and wiring are all live.\n')
        return 0
    sys.stdout.write(
        f'[agent-guard] UNGUARDED -- {len(report.failing)} of {len(report.parts)} part(s) are not the '
        f'installed guard: {", ".join(part.part for part in report.failing)}. An ABSENT or unreadable part '
        f'refuses nothing, and every agent command so far went through it; a FOREIGN one may well refuse '
        f'things, but it is enforcing a file nobody in this family can vouch for.\n'
        f'  Install with:  python -m lab_commons.dev.agent_guard --install --repo {report.repo}\n'
    )
    return 1


if __name__ == '__main__':
    raise SystemExit(report_guard())
