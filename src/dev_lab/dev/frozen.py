"""USER-FROZEN-FILES: a file the user finalized keeps its bytes, and no tracked path appears unapproved.

User ruling 2026-11-24: once the user finalizes a file it is FROZEN -- no modification -- and NO new git-tracked path
is added unless the user approved it. A repo opts in with a ``[tool.dev_lab.freeze]`` table in its
``pyproject.toml``; the facts are DATA in ONE file the table makes mandatory, :data:`FREEZE_FILE` at the root::

    tracked = [".vscode/settings.json", "freeze.toml", "pyproject.toml"]   # the CLOSED inventory

    [frozen]                                                               # path -> sha256 of its bytes
    ".vscode/settings.json" = "<64 hex>"
    "freeze.toml" = "self"

THE APPROVAL RECORD IS THE USER'S EDIT OF :data:`FREEZE_FILE`, and the file guards itself: it must list itself in
both ``tracked`` and ``[frozen]`` (as :data:`SELF`, since no file can hold its own hash), so every agent write to it
is refused. Three layers read this module (user refinement 2026-11-24, no server-side protection):

1. the agent hooks: the ``codeplace`` Write/Edit hook calls :func:`refuse_write`, and the shell deny row
   :mod:`dev_lab.dev._deny_frozen_row` asks :func:`main` ``--admit`` on a write-verb line;
2. the pre-commit row ``frozen-files`` (``main commit``) judges the INDEX against the INDEX's freeze file;
3. the always-on family check :func:`check` judges the checked-out tree, so the PR's own test run reds.

Every layer is one pure judgement, :func:`judge`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Final

from lab_commons.launch import run

from dev_lab.dev.family import declared_table

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

__all__ = [
    'FREEZE_FILE',
    'HAZARD',
    'REMEDY',
    'RULE_ID',
    'SELF',
    'Freeze',
    'check',
    'declared',
    'judge',
    'main',
    'parse',
    'refuse_write',
    'shell_targets',
]

RULE_ID: Final = 'USER-FROZEN-FILES'
FREEZE_FILE: Final = 'freeze.toml'
SELF: Final = 'self'
_TABLE: Final = 'freeze'
_SHA: Final = re.compile(r'[0-9a-f]{64}')
HAZARD: Final = 'a file the user finalized is frozen, and a tracked path exists only once the user approved it.'
REMEDY: Final = (
    f'Only the USER can unfreeze or approve: they edit {FREEZE_FILE} themselves (a `tracked` entry approves a path; '
    'a `[frozen]` row `"<path>" = "<sha256>"` freezes one, removing it unfreezes) and commit it. An agent asks the '
    f'user and never writes {FREEZE_FILE}.'
)


@dataclass(frozen=True, slots=True)
class Freeze:
    """The declaration: the closed tracked-path inventory and the frozen path -> sha256 map."""

    tracked: frozenset[str]
    frozen: Mapping[str, str]


def _refusal(what: str) -> str:
    return f'{RULE_ID}: {what} -- {HAZARD} {REMEDY}\ndetails: docs-src/dev/refusals.md#user-frozen-files (dev-lab)'


def parse(text: str) -> Freeze:
    """*text* of :data:`FREEZE_FILE` as a :class:`Freeze`; a malformed one raises ValueError naming the fault."""
    data = tomllib.loads(text)
    tracked, frozen = data.get('tracked'), data.get('frozen')
    if not isinstance(tracked, list) or not all(isinstance(item, str) and item for item in tracked):
        msg = f'{FREEZE_FILE}: `tracked` must be a list of repo-relative paths, not {tracked!r}'
        raise ValueError(msg)
    if not isinstance(frozen, dict) or not all(isinstance(v, str) for v in frozen.values()):
        msg = f'{FREEZE_FILE}: `[frozen]` must map repo-relative paths to sha256 hex strings, not {frozen!r}'
        raise ValueError(msg)
    if bad := sorted(p for p, sha in frozen.items() if p != FREEZE_FILE and not _SHA.fullmatch(sha)):
        msg = f'{FREEZE_FILE}: [frozen] {bad} carry no lowercase sha256 hex'
        raise ValueError(msg)
    if frozen.get(FREEZE_FILE) != SELF or FREEZE_FILE not in tracked:
        msg = f'{FREEZE_FILE} must freeze itself (`"{FREEZE_FILE}" = "{SELF}"` under [frozen]) and be in `tracked`'
        raise ValueError(msg)
    return Freeze(frozenset(tracked), dict(frozen))


def judge(freeze: Freeze, tracked: Iterable[str], read: Callable[[str], bytes]) -> list[str]:
    """Every violation of *freeze* by the *tracked* paths, whose bytes *read* returns; empty when none."""
    present = set(tracked)
    problems = [f'{p} is tracked but not in the approved inventory' for p in sorted(present - freeze.tracked)]
    for path, sha in sorted(freeze.frozen.items()):
        if sha == SELF:
            continue
        if path not in present:
            problems.append(f'{path} is frozen and was deleted')
        elif hashlib.sha256(read(path)).hexdigest() != sha:
            problems.append(f'{path} is frozen and its bytes changed')
    return problems


def declared(root: Path) -> bool:
    """Whether *root*'s ``pyproject.toml`` opts in with ``[tool.dev_lab.freeze]``; a broken manifest opts in."""
    try:
        data = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    except OSError:
        return False
    except ValueError:
        return True
    return declared_table(data, _TABLE) is not None


def _git(root: Path, *args: str) -> bytes:
    done = run(['git', *args], cwd=root, capture_output=True, check=False, timeout=60)
    if done.returncode != 0:
        msg = f'git {" ".join(args)} failed in {root}: {done.stderr.decode("utf-8", "replace").strip()}'
        raise RuntimeError(msg)
    return done.stdout


def _index_paths(root: Path) -> list[str]:
    return [p for p in _git(root, '-c', 'core.quotepath=off', 'ls-files', '-z').decode('utf-8').split('\0') if p]


def _problems(root: Path, *, index: bool) -> list[str]:
    """The violations in *root*: of the staged index (*index*) or of the checked-out tree."""
    if not declared(root):
        return []
    paths = _index_paths(root)
    if index:
        read: Callable[[str], bytes] = lambda p: _git(root, 'show', f':{p}')  # noqa: E731
    else:
        read = lambda p: (root / p).read_bytes()  # noqa: E731
    if FREEZE_FILE not in paths:
        return [f'[tool.dev_lab.{_TABLE}] is declared but {FREEZE_FILE} is not tracked']
    try:
        freeze = parse(read(FREEZE_FILE).decode('utf-8'))
    except ValueError as exc:
        return [str(exc)]
    return judge(freeze, paths, read)


def check(root: Path) -> None:
    """The always-on family check: raise naming every violation in *root*'s checked-out tree."""
    if problems := _problems(root, index=False):
        raise AssertionError(_refusal('; '.join(problems)))


def _frozen_of(path: Path) -> tuple[Path, Freeze] | None:
    from dev_lab.dev.gitdirs import checkout_of  # noqa: PLC0415 -- only a hook pays for it

    root = checkout_of(path.parent)
    if root is None or not declared(root):
        return None
    try:
        return root, parse((root / FREEZE_FILE).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def refuse_write(path: Path) -> str | None:
    """The refusal for an agent writing *path* when its checkout freezes it; ``None`` otherwise."""
    target = Path(path).resolve()
    found = _frozen_of(target)
    if found is None:
        return None
    root, freeze = found
    rel = target.relative_to(root.resolve()).as_posix()
    if rel in freeze.frozen:
        return _refusal(f'{rel} is frozen')
    return None


_SEGMENTS: Final = re.compile(r'&&|\|\||[;|\n]')
_REMOVERS: Final = frozenset({'mv', 'rm', 'touch', 'tee', 'truncate', 'Move-Item', 'Remove-Item', 'New-Item'})
_SETTERS: Final = frozenset({'Set-Content', 'Out-File', 'Add-Content', 'Clear-Content'})


def _operands(words: list[str]) -> list[str]:
    return [w for w in words if not w.startswith('-')]


def _redirects(words: list[str]) -> tuple[list[str], list[str]]:
    """The redirect targets among *words*, and the words left once the redirect operators are taken out."""
    targets: list[str] = []
    rest: list[str] = []
    for i, word in enumerate(words):
        match = re.fullmatch(r'\d?>>?(.*)', word)
        if match is None:
            rest.append(word)
        elif match.group(1) and not match.group(1).startswith('&'):
            targets.append(match.group(1))
        elif not match.group(1) and i + 1 < len(words):
            targets.append(words[i + 1])
    return targets, rest


def _verb_targets(words: list[str]) -> list[str]:
    """The operands a write verb at the head of *words* writes, moves or removes."""
    verb, args = words[0].rsplit('/', 1)[-1], words[1:]
    if verb == 'git' and args[:1] in (['rm'], ['mv']):
        verb, args = args[0], args[1:]
    if verb in _REMOVERS or verb in _SETTERS:
        return _operands(args)
    if verb == 'sed' and any(re.fullmatch(r'-[a-zA-Z]*i\S*', a) for a in args):
        return _operands(args)[1:]
    if verb in {'cp', 'Copy-Item'}:
        return _operands(args)[-1:]
    return []


def shell_targets(command: str) -> list[str]:
    """The paths *command* writes, moves or removes: redirect targets and the write verbs' operands."""
    found: list[str] = []
    for segment in _SEGMENTS.split(command):
        try:
            words = [w.strip('"\'') for w in shlex.split(segment, posix=False)]
        except ValueError:
            continue
        targets, rest = _redirects(words)
        found.extend(targets)
        if rest:
            found.extend(_verb_targets(rest))
    return found


def _shell_refusal(payload: Mapping[str, object]) -> str | None:
    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict):
        return None
    cwd = Path(str(payload.get('cwd') or Path.cwd()))
    for token in shell_targets(str(tool_input.get('command', ''))):
        target = Path(token).expanduser()
        if reason := refuse_write(target if target.is_absolute() else cwd / target):
            return reason
    return None


def main(argv: list[str] | None = None, *, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """``commit``: refuse the staged index (exit 1). ``--admit``: judge a shell hook payload on stdin (exit 1)."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.frozen', description=main.__doc__)
    parser.add_argument('mode', nargs='?', choices=('commit',))
    parser.add_argument('--admit', action='store_true')
    args = parser.parse_args(argv)
    out = stdout or sys.stdout.buffer
    if args.admit:
        try:
            payload = json.loads((stdin or sys.stdin.buffer).read().decode('utf-8'))
            reason = _shell_refusal(payload) if isinstance(payload, dict) else None
        except (ValueError, OSError, RuntimeError):
            return 0
    elif args.mode == 'commit':
        problems = _problems(Path.cwd(), index=True)
        reason = _refusal('; '.join(problems)) if problems else None
    else:
        parser.error('name a mode: commit or --admit')
    if reason is None:
        return 0
    out.write(reason.encode('utf-8') + b'\n')
    out.flush()
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
