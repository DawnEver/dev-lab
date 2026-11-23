"""WRITES-STAY-IN-THE-TREE: the write-prone roots outside every checkout, ONE declared set, three callers.

User requirement 2026-11-05: an agent session left scripts in the OS temp dir (Git Bash ``/tmp`` is the same directory
on Windows), and the other easy-to-write paths -- a drive's or the home's ``tmp``, ``temp``, ``var``, ``src``, and
the bare home -- must be checked the same way. A program's artefact goes to ``output/logs/<yy>/<mm>/<dd>/<kind>/``,
an experiment to ``scratch/``; outside a checkout nothing scans, ignores or cleans it.

THE SET IS DATA HERE (:func:`write_prone_roots`, :func:`excluded_paths`), the machine file's ``[writeroots]``
extends it (``temp``, ``census``, ``excluded``: lists of absolute paths). Three callers read it:

* the ``codeplace`` write hook (Write/Edit/MultiEdit/NotebookEdit) calls :func:`refuse_outside_tree`;
* the shell deny row :mod:`dev_lab.dev._deny_writeroots_row` spells the same roots as a pattern, because the
  engine reads text and has no filesystem;
* :mod:`dev_lab.dev.tmpsweep` is the census, the Stop report and the sweep.

A root's KIND decides what the sweep may do: ``temp`` is swept by age, ``census`` (``var``, ``src``: may hold a
person's work) and ``home`` (loose non-dot files directly in the home) are only ever reported.

ONLY OUR OWN IS SWEPT (user ruling 2026-11-11): a temp root is shared with every program on the machine -- an
installer's setup log, a browser's drag file, a runtime's cache -- and none of that is ours to delete (the sweep
kept tripping over the VS Code installer's locked log). The family creates its temp entries under ONE prefix,
:data:`lab_commons.temp.TEMP_PREFIX` (there because every repo's runtime code needs it and lab-commons never
imports dev-lab), and :func:`owned_globs` (that prefix, plus the machine file's ``[writeroots] owned`` globs for
a tool the family runs that names its own) is the whole of what the sweep may remove.

NO CHECKOUT EXEMPTION, in either half: a write beneath a write-prone root is refused EVEN INSIDE A CHECKOUT
there (user ruling 2026-11-06: a checkout under such a root, e.g. the home ``src``, is an abandoned old
version, never a place to work).
"""

from __future__ import annotations

import ctypes
import os
import string
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal

from lab_commons import storage as storages
from lab_commons.config import section
from lab_commons.storage import Storage
from lab_commons.temp import TEMP_PREFIX

from dev_lab.dev.disclosure import details_for

__all__ = [
    'DRIVE_NAMES',
    'EXCLUDED_GLOBS_IN_TEMP',
    'EXCLUDED_IN_TEMP',
    'HAZARD',
    'REMEDY',
    'RULE_ID',
    'Root',
    'declared',
    'excluded_paths',
    'fixed_drives',
    'owned_globs',
    'refuse_beside_checkout',
    'refuse_outside_tree',
    'refuse_synced',
    'synced_roots',
    'write_prone_roots',
]

RULE_ID: Final = 'WRITES-STAY-IN-THE-TREE'
HAZARD: Final = 'outside every checkout nothing scans, ignores or cleans a file, so it outlives the session.'
REMEDY: Final = (
    "No door: write in the checkout. A program's artefact goes to output/logs/<yy>/<mm>/<dd>/<kind>/, an "
    'experiment to scratch/ of the checkout you work in, a throwaway temp file to $CLAUDE_JOB_DIR/tmp.'
)
#: The environment variables naming a synced folder (OneDrive's client sets all three on Windows).
SYNCED_VARS: Final = ('OneDrive', 'OneDriveCommercial', 'OneDriveConsumer')
#: A synced folder by its segment name, for one no variable names (a second account, another machine's path).
_SYNCED_SEGMENT: Final = 'onedrive'
SYNCED_HAZARD: Final = (
    'a synced folder is shared mutable state with a live human session on the other end: your write races their '
    'save, their client decides who wins, and a rollback can vanish with it.'
)
SYNCED_REMEDY: Final = (
    'No agent door: read it freely; a write there is the user`s own -- hand them the path and content.'
)
BESIDE_HAZARD: Final = (
    'a directory beside a checkout is in no checkout: nothing scans, ignores or cleans it, and it reads as one more '
    'repository to whoever lists the parent.'
)
BESIDE_REMEDY: Final = (
    'No door: write in a checkout. Another tree of this repo is <repo>/.claude/worktrees/<name-for-the-task>; a '
    'family repo is cloned beside its siblings by git clone, never made by a write.'
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
    if env.get('CLAUDE_JOB_DIR'):
        found.append(Path(env['CLAUDE_JOB_DIR']) / 'tmp')  # the job's own temp: the door the remedy names
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


def refuse_outside_tree(
    path: Path, *, roots: Iterable[Root] | None = None, excluded: Iterable[Path] | None = None
) -> str | None:
    """The refusal for writing *path* into a write-prone root; ``None`` when it is not one.

    A checkout beneath the root changes nothing (user ruling 2026-11-06).

    A ``home`` root refuses only a loose non-dot entry directly in it; the others refuse anything beneath.
    """
    target = _norm(Path(path))
    roots = write_prone_roots() if roots is None else tuple(roots)
    excluded = excluded_paths(roots) if excluded is None else excluded
    if any(_within(target, _norm(one)) for one in excluded):
        return None
    for root in roots:
        base = _norm(root.path)
        loose = target.parent == base and not target.name.startswith('.')
        if loose if root.kind == 'home' else base in target.parents:
            where = f'{Path(path).as_posix()} is under {root.path.as_posix()}'
            return f'{RULE_ID}: {where} -- {HAZARD} {REMEDY}\n{details_for(RULE_ID)}'
    return None


def synced_roots(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """The synced folders this machine names: every :data:`SYNCED_VARS` that is set."""
    env = os.environ if env is None else env
    return tuple(dict.fromkeys(Path(env[var]) for var in SYNCED_VARS if env.get(var)))


def refuse_synced(path: Path, *, env: Mapping[str, str] | None = None) -> str | None:
    """The refusal for writing *path* into a synced folder (OneDrive), checkout or not; ``None`` otherwise.

    A synced folder is named by its variable, or by a segment starting ``OneDrive`` for one no variable names.
    """
    target = _norm(Path(path))
    named = any(_within(target, _norm(one)) for one in synced_roots(env))
    if named or any(part.lower().startswith(_SYNCED_SEGMENT) for part in target.parts[:-1]):
        where = f'{Path(path).as_posix()} is in a synced folder'
        return f'{RULE_ID}: {where} -- {SYNCED_HAZARD} {SYNCED_REMEDY}\n{details_for(RULE_ID)}'
    return None


def _is_checkout(folder: Path) -> bool:
    try:
        return (folder / '.git').exists()
    except OSError:
        return False


def refuse_beside_checkout(path: Path, *, excluded: Iterable[Path] | None = None) -> str | None:
    """The refusal for writing *path* into a directory BESIDE a checkout; ``None`` otherwise.

    Beside means: *path* lies in no checkout, and one of its non-dot ancestors sits in a directory that directly
    holds a checkout -- the ``../<repo>-copy`` an agent makes next to the repo it works in. A path in a checkout
    (a sibling repo's included) is that checkout's to judge; :func:`excluded_paths` (the job temp, bound storage)
    is never refused.
    """
    target = Path(path).resolve()
    if any(_is_checkout(folder) for folder in target.parents):
        return None
    excluded = excluded_paths(write_prone_roots()) if excluded is None else excluded
    if any(_within(_norm(target), _norm(one)) for one in excluded):
        return None
    above = target.parents[:-1]  # the drive root excluded
    if any(folder.name.startswith('.') for folder in above):
        return None  # a dot directory is tool state (a home's .claude, .cache), never a place an agent makes
    for folder in reversed(above):  # outermost first
        try:
            beside = [one for one in folder.parent.iterdir() if one != folder and one.is_dir() and _is_checkout(one)]
        except OSError:
            continue
        if beside:
            where = f'{target.as_posix()} is under {folder.as_posix()}, beside the checkout {beside[0].as_posix()}'
            return f'{RULE_ID}: {where} -- {BESIDE_HAZARD} {BESIDE_REMEDY}\n{details_for(RULE_ID)}'
    return None
