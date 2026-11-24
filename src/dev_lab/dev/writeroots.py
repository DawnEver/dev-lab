"""WRITES-STAY-IN-THE-TREE: an agent writes only into the roots its machine ALLOWS; everything else is refused.

User requirement 2026-11-05: an agent session left scripts in the OS temp dir (Git Bash ``/tmp`` is the same directory
on Windows). A program's artifact goes to ``output/logs/<yy>/<mm>/<dd>/<kind>/``, an experiment to ``scratch/``;
outside a checkout nothing scans, ignores or cleans it.

THE ALLOWLIST (ruling R8, 2026-11-24): the writable roots are a per-machine allowlist, declared in the config source
(``hosts/<machine>.toml`` ``[writeroots] allow``, rendered into the machine file), and EVERY other path is refused --
drive roots, ``~/src``, ``/tmp``, ``%TEMP%``, ``$CLAUDE_JOB_DIR/tmp``, OneDrive and a checkout's siblings above all.
An entry is an absolute path or a token (:data:`ALLOW_TOKENS`: ``{repos}`` -- every family checkout the machine
file's ``[repos]`` maps, its ``.claude/worktrees`` inside it; ``{lab_root}`` -- an HPC account's declared root).
UNDECLARED, the allowlist is ``{repos}`` alone, and the refusal says so. An entry no machine may allow (a drive root,
the home, a temp dir, ``src``, OneDrive: :func:`allow_defects`) is refused by name, in ``configcheck`` and here.
Admitted besides, as declared places and never strays: the tool caches, every bound storage root, ``[writeroots]
excluded`` and the harness's own plan files (:func:`admitted_paths`).

Two callers judge a write: the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls
:func:`refuse_outside_tree`, and the shell deny row :mod:`dev_lab.dev._deny_writeroots_row` prefilters a write whose
target may leave the tree and asks :func:`main` (``--admit``), which places each target (:func:`shell_targets`).

THE CENSUS is the other half: :func:`write_prone_roots` (the OS temp, POSIX ``/tmp`` ``/var/tmp``, each drive's and the
home's ``tmp``, ``temp``, ``var``, ``src``, the bare home, extended by ``[writeroots]`` ``temp``/``census``) is where
:mod:`dev_lab.dev.tmpsweep` LOOKS for strays. A root's KIND decides what the sweep may do: ``temp`` is swept by age,
``census`` (``var``, ``src``: may hold a person's work) and ``home`` (loose non-dot files) are only ever reported.

ONLY OUR OWN IS SWEPT (user ruling 2026-11-11): a temp root is shared with every program on the machine, and none of
that is ours to delete. The family creates its temp entries under ONE prefix, :data:`lab_commons.temp.TEMP_PREFIX`,
and :func:`owned_globs` (that prefix, plus ``[writeroots] owned``) is the whole of what the sweep may remove.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import string
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Final, Literal

from lab_commons import home as machine_home
from lab_commons import storage as storages
from lab_commons.config import section
from lab_commons.hpc.layout import ROOT_VAR as LAB_ROOT_VAR
from lab_commons.storage import Storage
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.disclosure import details_for

__all__ = [
    'ALLOW_TOKENS',
    'DOOR',
    'DRIVE_NAMES',
    'EXCLUDED_GLOBS_IN_TEMP',
    'EXCLUDED_IN_TEMP',
    'HAZARD',
    'REMEDY',
    'RULE_ID',
    'Allowance',
    'Root',
    'admitted_paths',
    'allow_defects',
    'allowed_roots',
    'declared',
    'excluded_paths',
    'fixed_drives',
    'judge',
    'owned_globs',
    'place',
    'refuse_outside_tree',
    'shell_targets',
    'write_prone_roots',
]

RULE_ID: Final = 'WRITES-STAY-IN-THE-TREE'
HAZARD: Final = 'outside every checkout nothing scans, ignores or cleans a file, so it outlives the session.'
REMEDY: Final = (
    "No door: write in the checkout. A program's artifact goes to output/logs/<yy>/<mm>/<dd>/<kind>/, an "
    'experiment to scratch/ of the checkout you work in (user ruling 2026-11-23: no job temp dir either).'
)

#: Directory names that are write-prone at a drive root and in the home, and the KIND each is.
DRIVE_NAMES: Final[Mapping[str, Literal['temp', 'census']]] = {
    'tmp': 'temp',
    'temp': 'temp',
    'var': 'census',  # may hold a service's data: reported, never swept
    'src': 'census',  # may hold a person's checkouts: reported, never swept
}

#: Names under a TEMP root that are never refused, reported or swept, each with its reason.
EXCLUDED_IN_TEMP: Final[Mapping[str, str]] = {
    'claude': 'the Claude Code harness writes its task output under <temp>/claude/<hash>/<session>/ itself',
    'lab-commons-notices': "dev_lab.dev.branchnotices' per-session forge-read cache",
    'claude-notif-*.ps1': 'the Claude Code harness writes its desktop-notification script here itself',
}

#: The :data:`EXCLUDED_IN_TEMP` names that are GLOBS (a harness file named at random), matched against an entry's
#: name; the rest are exact names, excluded as paths (:func:`excluded_paths`).
EXCLUDED_GLOBS_IN_TEMP: Final = tuple(name for name in EXCLUDED_IN_TEMP if any(c in name for c in '*?['))

#: Environment variables naming a tool cache the family uses; one inside a root is excluded.
_CACHE_VARS: Final = ('UV_CACHE_DIR', 'PIP_CACHE_DIR', 'RUFF_CACHE_DIR')
_TEMP_VARS: Final = ('TEMP', 'TMP', 'TMPDIR')
_POSIX_TEMP: Final = (Path('/') / 'tmp', Path('/') / 'var' / 'tmp')
_FIXED_DRIVE: Final = 3  # GetDriveTypeW's DRIVE_FIXED


@dataclass(frozen=True, slots=True)
class Root:
    """One write-prone root: its path, and whether the sweep may age entries out of it."""

    path: Path
    kind: Literal['temp', 'census', 'home']


def fixed_drives() -> list[Path]:
    """Every fixed drive's root on Windows (``C:/``, ``D:/`` ...); none elsewhere."""
    if os.name != 'nt':
        return []
    kernel = ctypes.WinDLL('kernel32')
    return [Path(f'{d}:/') for d in string.ascii_uppercase if kernel.GetDriveTypeW(f'{d}:\\') == _FIXED_DRIVE]


def declared() -> dict[str, Any]:
    """The machine file's ``[writeroots]`` table (``temp``, ``census``, ``excluded``, ``owned``), or ``{}``."""
    return section('writeroots')


def owned_globs(machine: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """The name globs of a temp root's entries that are OURS: :data:`TEMP_PREFIX`, plus ``[writeroots] owned``."""
    machine = declared() if machine is None else machine
    extra = machine.get('owned', [])
    if not isinstance(extra, list) or not all(isinstance(one, str) and one for one in extra):
        msg = f'[writeroots] owned is {extra!r}; it must be a list of entry-name globs (e.g. "pytest-of-*")'
        raise ValueError(msg)
    return (f'{TEMP_PREFIX}*', *extra)


def _paths(machine: Mapping[str, Any], key: str) -> list[Path]:
    value = machine.get(key, [])
    if not isinstance(value, list) or not all(isinstance(one, str) for one in value):
        msg = f'[writeroots] {key} is {value!r}; it must be a list of absolute paths'
        raise ValueError(msg)
    return [Path(one).expanduser() for one in value]


def write_prone_roots(
    *,
    temp_dirs: Iterable[Path] | None = None,
    home: Path | None = None,
    drives: Iterable[Path] | None = None,
    posix: bool | None = None,
    machine: Mapping[str, Any] | None = None,
) -> tuple[Root, ...]:
    """THE SET: OS temp, POSIX ``/tmp`` ``/var/tmp``, each drive's and the home's :data:`DRIVE_NAMES`, the home.

    Every argument defaults to this machine; a test injects all of them.
    """
    if temp_dirs is None:
        temp_dirs = [Path(tempfile.gettempdir()), *(Path(v) for k in _TEMP_VARS if (v := os.environ.get(k)))]
    home = Path.home() if home is None else home
    drives = fixed_drives() if drives is None else drives
    machine = declared() if machine is None else machine
    roots = [Root(Path(p), 'temp') for p in temp_dirs]
    if os.name != 'nt' if posix is None else posix:
        roots += [Root(p, 'temp') for p in _POSIX_TEMP]
    roots += [Root(base / name, kind) for base in (*drives, home) for name, kind in DRIVE_NAMES.items()]
    roots.append(Root(home, 'home'))
    roots += [Root(p, 'temp') for p in _paths(machine, 'temp')]
    roots += [Root(p, 'census') for p in _paths(machine, 'census')]
    return tuple(dict.fromkeys(roots))


def excluded_paths(
    roots: Iterable[Root],
    *,
    machine: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
    storage: Storage | None = None,
) -> tuple[Path, ...]:
    """What no caller refuses, reports or sweeps: :data:`EXCLUDED_IN_TEMP`, the cache variables, the machine's.

    The machine's are its ``[writeroots] excluded`` and every root it binds a storage kind to
    (:mod:`lab_commons.storage`): a declared place, never a stray.
    """
    env = os.environ if env is None else env
    machine = declared() if machine is None else machine
    names = [name for name in EXCLUDED_IN_TEMP if name not in EXCLUDED_GLOBS_IN_TEMP]  # a glob is matched by name
    found = [root.path / name for root in roots if root.kind == 'temp' for name in names]
    found += [Path(env[var]) for var in _CACHE_VARS if env.get(var)]
    found += _paths(machine, 'excluded')
    found += storage_roots(storages.declared() if storage is None else storage)
    return tuple(dict.fromkeys(found))


def storage_roots(storage: Storage) -> list[Path]:
    """Every bound storage root; a ``{repo}`` placeholder admits every repo's directory under the part before it."""
    return [Path(value.split('{repo}', 1)[0]).expanduser() for value in storage.roots.values()]


def _within(path: Path, base: Path) -> bool:
    return path == base or base in path.parents


def _norm(path: Path) -> Path:
    return Path(os.path.normcase(Path(path).resolve()))


# ---------------------------------------------------------------- THE ALLOWLIST (ruling R8, 2026-11-24)

#: The tokens an ``allow`` entry may name instead of a path, each with what it stands for.
ALLOW_TOKENS: Final[Mapping[str, str]] = {
    '{repos}': "every family checkout the machine file's [repos] maps (its .claude/worktrees inside it)",
    '{lab_root}': "an HPC account's declared root (LAB_ROOT, which its deploy sets)",
}
#: Path segments no allowed root may be or lie under, each with its reason.
_NEVER_SEGMENTS: Final[Mapping[str, str]] = {
    'tmp': 'a temp dir is shared with every program on the machine',
    'temp': 'a temp dir is shared with every program on the machine',
    'src': 'a checkout under src is an abandoned old version (user ruling 2026-11-06)',
}
_ABSOLUTE: Final = re.compile(r'^(?:[A-Za-z]:/|/|~)')
_DRIVE_ROOT: Final = re.compile(r'^(?:[A-Za-z]:|/[A-Za-z]?|)$')
_HOME: Final = re.compile(r'^(?:~|[A-Za-z]:/Users/[^/]+|/home/[^/]+|/Users/[^/]+|/gpfs\d*/home/[^/]+)$', re.IGNORECASE)
DOOR: Final = (
    'declare it in the config source -- hosts/<machine>.toml [writeroots] allow, through its pull request -- then '
    'python -m dev_lab.dev.devhost render --host <machine> --from <clone> --write'
)


def allow_defects(entries: object) -> list[str]:
    """Why each ``[writeroots] allow`` entry is refused, judged on its SPELLING (``configcheck`` runs on any OS).

    Refused: a non-list, a non-string, a relative path, an unknown token, a drive root, the home itself, and anything
    at or under a ``tmp``/``temp``/``src`` segment or a OneDrive folder.
    """
    if not isinstance(entries, list):
        return [f'[writeroots] allow is {entries!r}; it must be a list of absolute paths or {sorted(ALLOW_TOKENS)}']
    found = []
    for entry in entries:
        if not isinstance(entry, str) or not entry.strip():
            found.append(f'[writeroots] allow entry {entry!r} must be a non-empty string')
            continue
        if entry.startswith('{'):
            if entry not in ALLOW_TOKENS:
                found.append(f'[writeroots] allow entry {entry!r} is no token; the tokens are {sorted(ALLOW_TOKENS)}')
        elif never := _never(entry):
            found.append(f'[writeroots] allow entry {entry!r} is refused: {never}')
    return found


def _never(entry: str) -> str | None:
    """Why the path *entry* can never be a writable root, or ``None``."""
    spelled = entry.replace('\\', '/').rstrip('/')
    segments = [one.casefold() for one in spelled.split('/')]
    if not _ABSOLUTE.match(entry.replace('\\', '/')):
        return 'it is not an absolute path'
    if _DRIVE_ROOT.match(spelled):
        return 'it is a drive root'
    if _HOME.match(spelled):
        return 'it is the home itself'
    if any(one.startswith('onedrive') for one in segments):
        return 'OneDrive is a synced folder with a live human session on the other end'
    return next((why for one in segments if (why := _NEVER_SEGMENTS.get(one))), None)


@dataclass(frozen=True, slots=True)
class Allowance:
    """The roots an agent may write into, and where the list came from: ``declared``, or the ``fallback``."""

    roots: tuple[Path, ...]
    source: Literal['declared', 'fallback']


def allowed_roots(
    *,
    machine: Mapping[str, Any] | None = None,
    repos: Mapping[str, Path] | None = None,
    env: Mapping[str, str] | None = None,
) -> Allowance:
    """The machine's allowlist: ``[writeroots] allow`` with its tokens expanded; undeclared, ``{repos}`` alone.

    A defective declaration raises ``ValueError`` naming each entry (:func:`allow_defects`), never a silent widening.
    """
    machine = declared() if machine is None else machine
    env = os.environ if env is None else env
    entries = machine.get('allow')
    source: Literal['declared', 'fallback'] = 'fallback' if entries is None else 'declared'
    entries = ['{repos}'] if entries is None else entries
    if defects := allow_defects(entries):
        msg = f'{"; ".join(defects)} -- {DOOR}'
        raise ValueError(msg)
    repos = machine_home.repos() if repos is None else repos
    roots: list[Path] = []
    for entry in entries:
        if entry == '{repos}':
            roots += [Path(one) for one in repos.values()]
        elif entry == '{lab_root}':
            roots += [Path(env[LAB_ROOT_VAR]).expanduser()] if env.get(LAB_ROOT_VAR) else []
        else:
            roots.append(Path(entry).expanduser())
    return Allowance(tuple(dict.fromkeys(roots)), source)


def admitted_paths(
    *, machine: Mapping[str, Any] | None = None, env: Mapping[str, str] | None = None, storage: Storage | None = None
) -> tuple[Path, ...]:
    """Declared places a write may land outside the allowlist.

    They are the tool caches, every bound storage root, ``[writeroots] excluded``, and the harness's plan directory
    (the harness tells the agent to write its plan there). Never the harness's temp subtree: the harness writes there
    itself, and an agent's write there (a ``$CLAUDE_JOB_DIR/tmp`` above all) is a stray like any other (ruling R8).
    """
    env = os.environ if env is None else env
    machine = declared() if machine is None else machine
    config = Path(env['CLAUDE_CONFIG_DIR']) if env.get('CLAUDE_CONFIG_DIR') else Path.home() / '.claude'
    found = [Path(env[var]) for var in _CACHE_VARS if env.get(var)]
    found += _paths(machine, 'excluded')
    found += storage_roots(storages.declared() if storage is None else storage)
    found.append(config.expanduser() / 'plans')
    return tuple(dict.fromkeys(found))


def refuse_outside_tree(
    path: Path, *, allowed: Allowance | None = None, admitted: Iterable[Path] | None = None
) -> str | None:
    """The refusal for writing *path* outside every allowed root and admitted place; ``None`` inside one.

    A checkout's sibling, a drive root, the temp dir, OneDrive: all are simply not on the list.
    """
    target = _norm(Path(path))
    try:
        allowed = allowed_roots() if allowed is None else allowed
    except ValueError as defect:
        return f'{RULE_ID}: this machine declares an unusable allowlist: {defect}\n{details_for(RULE_ID)}'
    admitted = admitted_paths() if admitted is None else admitted
    if any(_within(target, _norm(one)) for one in (*allowed.roots, *admitted)):
        return None
    if allowed.source == 'declared':
        whose = "this machine's [writeroots] allow"
    else:
        whose = 'the fallback, the family checkouts of [repos] ([writeroots] allow is undeclared here)'
    listed = ', '.join(root.as_posix() for root in allowed.roots) or 'none'
    return (
        f'{RULE_ID}: {Path(path).as_posix()} is outside every writable root of {whose}: {listed} -- {HAZARD} '
        f'{REMEDY} A root this machine truly needs: {DOOR}.\n{details_for(RULE_ID)}'
    )


# ---------------------------------------------------------------- THE SHELL HALF: place each target a line writes

_TOKEN: Final = re.compile(r"""\d?>>?|&>>?|\|\||&&|[|;&\n]|<<?|(?:"(?:[^"\\]|\\.)*"|'[^']*'|[^\s|;&<>"'])+""")
_HEREDOC: Final = re.compile(r"""<<-?\s*(["']?)([A-Za-z_][A-Za-z0-9_]*)\1""")
_REDIRECT: Final = re.compile(r'\d?>>?|&>>?')
_SEPARATORS: Final = frozenset({'|', '||', '&&', ';', '&', '\n'})
_DISCARDS: Final = frozenset({'/dev/null', '/dev/stdout', '/dev/stderr', '/dev/tty', 'nul', '$null'})
_CD: Final = frozenset({'cd', 'pushd', 'set-location', 'sl', 'chdir'})
_EACH_OPERAND: Final = frozenset({'mkdir', 'touch', 'tee'})
_LAST_OPERAND: Final = frozenset({'cp', 'mv', 'copy', 'move', 'rsync', 'install', 'copy-item', 'move-item'})
_PS_WRITERS: Final = frozenset({'new-item', 'ni', 'out-file', 'set-content', 'add-content'})
_PS_PATH: Final = frozenset({'-path', '-filepath', '-literalpath', '-destination'})
#: PowerShell writer options that take a value, which is no target.
_PS_VALUED: Final = frozenset({'-itemtype', '-type', '-value', '-encoding', '-inputobject', '-name'})


def _without_heredoc_bodies(command: str) -> str:
    """*command* without its heredoc BODIES; the opening line stays whole, a redirect after ``<<EOF`` included."""
    out, index = '', 0
    for match in _HEREDOC.finditer(command):
        if match.start() < index:
            continue
        body = command.find('\n', match.end())
        if body == -1:
            break
        closer = re.compile(rf'^[ \t]*{re.escape(match.group(2))}[ \t]*$', re.MULTILINE)
        end = closer.search(command, body + 1)
        out += command[index:body] + '\n'
        index = len(command) if end is None else end.end()
    return out + command[index:]


def _unquote(token: str) -> str:
    return ''.join(
        part[1:-1] if part[:1] in '"\'' else part for part in re.findall(r'"[^"]*"|\'[^\']*\'|[^"\']+', token)
    )


def _absolute(text: str) -> bool:
    return bool(re.match(r'^(?:[A-Za-z]:[\\/]|[\\/]|~|\$|%)', text))


def _segment_targets(words: list[str], cwd: str, found: list[tuple[str, str]]) -> str:
    """Append the targets one command segment (*words*) writes to *found*; return the cwd after it."""
    if not words:
        return cwd
    verb = words[0].replace('\\', '/').rsplit('/', 1)[-1].casefold()
    operands = [one for one in words[1:] if not one.startswith('-')]
    if verb in _CD and operands:
        return operands[0] if not cwd or _absolute(operands[0]) else f'{cwd}/{operands[0]}'
    if verb in _EACH_OPERAND:
        found.extend((one, cwd) for one in operands)
    elif verb in _LAST_OPERAND and len(operands) > 1:
        found.append((operands[-1], cwd))
    elif verb == 'dd':
        found.extend((one[3:], cwd) for one in words[1:] if one.startswith('of='))
    elif verb in _PS_WRITERS:
        named = [words[i + 1] for i, one in enumerate(words[:-1]) if one.casefold() in _PS_PATH]
        valued = {i + 1 for i, one in enumerate(words) if one.casefold() in _PS_VALUED}
        positional = [one for i, one in enumerate(words) if i and i not in valued and not one.startswith('-')]
        found.extend((one, cwd) for one in (named or positional[:1]))
    return cwd


def shell_targets(command: str) -> list[tuple[str, str]]:
    """Each (target, the cwd it is relative to -- ``''`` for the call's own) a shell line writes, as spelled.

    Read: a redirect (``>``, ``>>``, ``2>``, ``&>``), ``tee``/``mkdir``/``touch`` operands, the last operand of a
    copy or move, ``dd of=``, a PowerShell writer's ``-Path``/``-FilePath``/``-Destination`` or first operand; a
    ``cd``/``pushd``/``Set-Location`` moves the cwd later targets are relative to. A discard (``/dev/null``) is none.
    """
    found: list[tuple[str, str]] = []
    cwd = ''
    segment: list[str] = []
    redirect = False
    for token in [*_TOKEN.findall(_without_heredoc_bodies(command)), '\n']:
        if redirect:
            redirect = False
            if not token.startswith('&'):
                found.append((_unquote(token), cwd))
        elif _REDIRECT.fullmatch(token):
            redirect = True
        elif token in _SEPARATORS:
            cwd = _segment_targets([_unquote(one) for one in segment], cwd, found)
            segment = []
        elif token not in ('<', '<<'):
            segment.append(token)
    return [(target, where) for target, where in found if target and target.casefold() not in _DISCARDS]


def place(target: str, cwd: str, base: Path, *, env: Mapping[str, str] | None = None) -> Path | None:
    """The path *target* names (relative to *cwd* as spelled, itself relative to *base*); ``None`` if unplaceable.

    Expands ``$NAME``, ``${NAME}``, ``$env:NAME``, ``%NAME%`` and ``~``; a variable this process does not hold is
    unplaceable. On Windows, Git Bash's ``/tmp`` is the OS temp dir and ``/c/...`` is ``C:/...``.
    """
    env = os.environ if env is None else env
    folded = {key.casefold(): value for key, value in env.items()}

    def expand(text: str) -> str | None:
        names = re.findall(r'\$\{(\w+)\}|\$env:(\w+)|\$(\w+)|%(\w+)%', text, flags=re.IGNORECASE)
        if any(''.join(one).casefold() not in folded for one in names):
            return None
        text = re.sub(
            r'\$\{(\w+)\}|\$env:(\w+)|\$(\w+)|%(\w+)%',
            lambda m: folded[''.join(m.groups(default='')).casefold()].replace('\\', '/'),
            text,
            flags=re.IGNORECASE,
        ).replace('\\', '/')
        if os.name == 'nt':
            if text == '/tmp' or text.startswith('/tmp/'):  # noqa: S108 -- Git Bash's spelling, translated, never used
                text = Path(tempfile.gettempdir()).as_posix() + text[4:]
            elif drive := re.match(r'^/([A-Za-z])(?:/|$)', text):
                text = f'{drive.group(1).upper()}:/{text[3:]}'
        return text

    where, spelled = expand(cwd), expand(target)
    if where is None or spelled is None:
        return None
    path = Path(spelled).expanduser()
    if path.is_absolute():
        return path
    return base / Path(where).expanduser() / path if where else base / path


def judge(
    payload: Mapping[str, Any], *, allowed: Allowance | None = None, admitted: Iterable[Path] | None = None
) -> str | None:
    """The refusal for the shell call in hook *payload*, or ``None``: every target it writes is placed and judged."""
    tool_input = payload.get('tool_input')
    command = tool_input.get('command') if isinstance(tool_input, Mapping) else None
    if not isinstance(command, str):
        return None
    base = Path(str(payload.get('cwd') or Path.cwd()))
    for target, cwd in shell_targets(command):
        path = place(target, cwd, base)
        if path is None:
            spelled = f'{cwd}/{target}' if cwd else target
            return (
                f'{RULE_ID}: {spelled} names a variable this session does not hold, so no writable root can be '
                f'shown to hold it -- {REMEDY}\n{details_for(RULE_ID)}'
            )
        if reason := refuse_outside_tree(path, allowed=allowed, admitted=admitted):
            return reason
    return None


def main(argv: list[str] | None = None, *, stdin: BinaryIO | None = None, stdout: BinaryIO | None = None) -> int:
    """``--admit``: judge the shell hook payload on stdin; exit 1 with the refusal on stdout, else 0."""
    parser = argparse.ArgumentParser(prog='python -m dev_lab.dev.writeroots', description=main.__doc__)
    parser.add_argument('--admit', action='store_true', required=True)
    parser.parse_args(argv)
    try:
        payload = json.loads((stdin or sys.stdin.buffer).read().decode('utf-8'))
    except ValueError:
        return 0
    reason = judge(payload) if isinstance(payload, dict) else None
    if reason is None:
        return 0
    out = stdout or sys.stdout.buffer
    out.write(reason.encode('utf-8'))
    out.flush()
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
