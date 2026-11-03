"""WRITE-OUTSIDE-ROOTS: an agent writes only into a configured repo or the machine home (user ruling 2026-11-03).

THE RULE. Every file an agent writes -- temporary files included -- lands in a configured repo or in the machine
home (:mod:`lab_commons.home`, whose ``[repos]`` table is the one source of where each checkout is). Inside a
repo, development is the repo's own business (an untracked file is :mod:`dev_lab.dev.codeplace`'s stray census),
but its two write sinks have shapes, held here:

* ``scratch/`` holds SCRIPTS ONLY, at ``scratch/<yy>/<mm>/<dd>/<kind>/`` (:func:`dev_lab.dev.scratch.is_dated_script`,
  made by ``python -m dev_lab.dev.scratch new <kind> <name>``);
* ``output/`` holds OUTPUTS ONLY: never a script (:data:`dev_lab.dev.scratch.SCRIPT_SUFFIXES`).

A synced folder (OneDrive) is refused unless the user consents to that write. Claude's configuration and the agent
repos are outside the policy (:func:`lab_commons.home.exempt`).

WHAT IS JUDGED. A ``PreToolUse`` payload: ``Write``/``Edit``/``MultiEdit``/``NotebookEdit`` by their path, and a
``Bash``/``PowerShell`` command by the targets it CLEARLY writes -- a redirection, ``tee``, ``Out-File``,
``Set-Content``/``Add-Content``, ``mkdir``/``New-Item``, ``touch``, the destination of ``cp``/``mv``/``Copy-Item``/
``Move-Item``, and a literal ``open(<path>, 'w'|'a'|'x')``. A target spelled through a variable is not judged here:
the census (stray roots, swept on the serve tick) is the backstop for what no parser can see. Relative targets
resolve against the payload's ``cwd``.

THE POLICY IS DATA (:class:`Policy`), built from the machine (:func:`machine_policy`) and injected in tests, so the
rules are proven without a machine file.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, TextIO

from lab_commons.log import emit

from dev_lab.dev.scratch import SCRIPT_SUFFIXES, is_dated_script

__all__ = ['RULE', 'Policy', 'machine_policy', 'main', 'refusal', 'targets']

RULE: Final = 'WRITE-OUTSIDE-ROOTS'

#: The file tools and the key that names their target.
_FILE_TOOLS: Final = {
    'Write': 'file_path',
    'Edit': 'file_path',
    'MultiEdit': 'file_path',
    'NotebookEdit': 'notebook_path',
}
_SHELL_TOOLS: Final = frozenset({'Bash', 'PowerShell'})
#: Sinks that discard, never write a file.
_NULL: Final = frozenset({'/dev/null', 'nul', '$null'})

_REDIRECT: Final = re.compile(r"""(?<![<>&\d])(?:\d|&)?>>?(?!&|\()\s*(?P<t>"[^"]+"|'[^']+'|[^\s;&|<>()]+)""")
_OPEN: Final = re.compile(r"""\bopen\(\s*r?(['"])(?P<t>[^'"]+)\1\s*,\s*r?(['"])[^'"]*[wax][^'"]*\3""")
_SEGMENT: Final = re.compile(r'\s*(?:&&|\|\||[;|\n])\s*')
_TARGET_FLAGS: Final = {'-filepath', '-path', '-literalpath', '-destination'}


@dataclass(frozen=True)
class Policy:
    """What the machine allows: write roots, exemptions, repos, tracked files and consent-only trees."""

    allowed: Callable[[Path], bool]
    exempt: Callable[[Path], bool]
    repo_of: Callable[[Path], Path | None]
    tracked: Callable[[Path], bool]
    consent: tuple[Path, ...]


def machine_policy() -> Policy:
    """The policy of the machine this runs on: :mod:`lab_commons.home` and the user's OneDrive roots."""
    from lab_commons import home  # noqa: PLC0415 -- the hook reads the machine only when it runs

    consent = tuple(Path(os.environ[name]) for name in ('OneDrive', 'OneDriveCommercial') if os.environ.get(name))
    return Policy(allowed=home.allowed, exempt=home.exempt, repo_of=home.repo_of, tracked=_tracked, consent=consent)


def _tracked(path: Path) -> bool:
    from lab_commons import launch  # noqa: PLC0415

    done = launch.run(['git', '-C', str(path.parent), 'ls-files', '--error-unmatch', path.name], check=False)
    return done.returncode == 0


def _resolve(raw: str, cwd: Path) -> Path | None:
    word = raw.strip('\'"')
    if not word or word.lower() in _NULL or '$' in word or '%' in word or word.startswith('-'):
        return None
    path = Path(word).expanduser()
    return Path(os.path.normpath(path if path.is_absolute() else cwd / path))


def _shell_words(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=True)
    except ValueError:
        return segment.split()


def _segment_targets(words: list[str]) -> list[str]:
    if not words:
        return []
    verb, rest = words[0].lower(), words[1:]
    flagged = [rest[i + 1] for i, word in enumerate(rest[:-1]) if word.lower() in _TARGET_FLAGS]
    plain = [word for word in rest if not word.startswith('-')]
    if verb == 'tee' or verb in {'mkdir', 'touch', 'md'}:
        return plain
    if verb in {'cp', 'mv', 'copy-item', 'move-item', 'copy', 'move'}:
        return flagged or plain[-1:]
    if verb in {'out-file', 'set-content', 'add-content', 'new-item'}:
        return flagged or plain[:1]
    return []


def targets(command: str, cwd: Path) -> list[Path]:
    """The paths *command* clearly writes, resolved against *cwd*."""
    raw = [m['t'] for m in _REDIRECT.finditer(command)] + [m['t'] for m in _OPEN.finditer(command)]
    stripped = _REDIRECT.sub(' ', command)
    for segment in _SEGMENT.split(stripped):
        raw.extend(_segment_targets(_shell_words(segment)))
    return [path for path in (_resolve(word, cwd) for word in raw) if path is not None]


def _in_repo(path: Path, repo: Path, policy: Policy) -> str | None:
    scratch, output = repo / 'scratch', repo / 'output'
    if scratch == path or scratch in path.parents:
        if policy.tracked(path) or is_dated_script(path.relative_to(scratch).as_posix()):
            return None
        return (
            f'{RULE} (SCRATCH): {path} -- scratch holds scripts only, at scratch/<yy>/<mm>/<dd>/<kind>/; '
            'make one with: python -m dev_lab.dev.scratch new <kind> <name> (data belongs in output/)'
        )
    if (output == path or output in path.parents) and path.suffix.lower() in SCRIPT_SUFFIXES:
        return f'{RULE} (OUTPUT): {path} -- output holds outputs only; a script goes to scratch (scratch new)'
    return None


def _judge(path: Path, policy: Policy) -> str | None:
    if policy.exempt(path):
        return None
    repo = policy.repo_of(path)
    if repo is not None:
        return _in_repo(path, repo, policy)
    if policy.allowed(path):
        return None
    if any(root == path or root in path.parents for root in policy.consent):
        return f'{RULE}: {path} is in a synced folder -- write there only with the user consent for this write'
    return (
        f'{RULE}: {path} is outside every write root -- write into the repo (output/ for outputs and temp, '
        'scratch/ for scripts) or the machine home; the roots are [repos] of the machine file'
    )


def refusal(payload: dict[str, Any], policy: Policy) -> str | None:
    """The refusal for *payload*, or ``None`` when every target it writes is allowed."""
    tool, given = payload.get('tool_name'), payload.get('tool_input') or {}
    cwd = Path(payload.get('cwd') or Path.cwd())
    if tool in _FILE_TOOLS:
        raw = given.get(_FILE_TOOLS[tool])
        paths = [] if not raw else [Path(os.path.normpath(Path(raw) if Path(raw).is_absolute() else cwd / raw))]
    elif tool in _SHELL_TOOLS:
        paths = targets(str(given.get('command') or ''), cwd)
    else:
        return None
    for path in paths:
        found = _judge(path, policy)
        if found is not None:
            return found
    return None


def main(argv: list[str] | None = None, *, stdin: TextIO | None = None) -> int:
    """The ``PreToolUse`` hook: exit 2 with the refusal on stderr, else 0. An unreadable payload is not judged."""
    del argv
    try:
        payload = json.load(stdin or sys.stdin)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    found = refusal(payload, machine_policy())
    if found is None:
        return 0
    emit(found, err=True)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
