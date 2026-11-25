"""ONE CALENDAR for everything a dev harness writes -- ``<base>/<yy>/<mm>/<dd>/<kind>/<name>``.

Migrated 2026-09-17 from consumer-a's ``scripts/gate/_dated.py``, where FOUR harnesses had
implemented the same layout independently (a gate runner, a pre-push gate, a measurement harness and
an output-hygiene sweeper). Four calendars that can drift apart, and four docstrings asserting the
same layout, is the duplication this module ends.

**THE BASE IS THE REPO'S ANSWER AND HAS NO DEFAULT**, and that is a MEASUREMENT rather than caution.
consumer-a writes under ``output/logs/`` because a user directive said so on 2026-09-03; when this
was migrated this very package wrote its verify log to ``.verify/`` (retired 2026-11-05) and the two labs
had no dated tree at all. Today every family repo declares ``output = "output/logs"``, and a default here
would still hand an undeclared repo another repo's answer while looking like a shared convention.
What IS universal is the partition -- a date taken once, a kind beneath it, and a NAME that may not
escape either.

THE REPO'S ANSWER IS ``[tool.dev_lab.parts] output`` (every family repo declares ``"output/logs"``), read by
:func:`declared_output`; :func:`output_dir` is the dated directory under it, for every artifact a program
produces and can regenerate (verify's run log and records, its coverage, the durations ledger, part records).
An undeclared output is REFUSED naming the key, never defaulted, for the reason above.

WHAT THIS IS NOT. It does not name a verdict, address a tree, or stamp a log: a log's CONTENT and
its citation belong to :mod:`dev_lab.dev.logref`, and this answers only where the file sits.

A NAME, NEVER A PATH, AND THERE IS NO EXEMPTION. The version this was migrated from had carried two
escape hatches and had them removed on 2026-09-08 after neither checked the thing it excused: an
``is_absolute()`` branch excused every path merely spelled in full, and a ``'logs' in parts`` branch
matched the segment anywhere, so ``logs/x.log`` passed while being no more dated than a bare name.
They are not reinstated here. An undated artifact cannot be told from one an abandoned lane left
behind, and a sweeper cannot age out a file with no age.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final

from lab_commons import storage as _storage

from dev_lab.dev.family import declared_in
from dev_lab.dev.storage import output_path

if TYPE_CHECKING:
    pass

__all__ = [
    'FAMILY_KINDS',
    'OUTPUT_KEY',
    'UndeclaredOutput',
    'date_parts',
    'dated_base',
    'dated_log',
    'declared_output',
    'output_dir',
]

#: The one key a repo answers "where does dated output live" with.
OUTPUT_KEY: Final = '[tool.dev_lab.parts] output'

#: THE FAMILY'S DATED KINDS, declared ONCE: every ``<output>/<yy>/<mm>/<dd>/<kind>/`` a dev-lab mechanism writes, ->
#: its shapes (``'.'`` the kind directory itself, else a per-segment glob below it) -> the suffixes a file there may
#: have (an empty set: directories only). Every adopter's layout (:mod:`dev_lab.dev.layout`) admits these without
#: listing them and refuses a row of its own naming one; a repo lists only its own kinds. A writer of a kind absent
#: here reds ``tests/test_arch_family_kinds_are_declared_once.py``.
FAMILY_KINDS: Final[dict[str, dict[str, frozenset[str]]]] = {
    # verifysteps: the run log, its box outcome records, the serial-pass marker; test_outcomes: each stage's cells.
    'verify': {
        '.': frozenset({'.log', '.json', '.serial-seen'}),
        '*.outcomes': frozenset(),
        '*.outcomes/*': frozenset({'.jsonl'}),
    },
    'coverage': {'.': frozenset({'.md', '.coverage'})},  # _verify_coverage: the table and its data file
    'durations': {'.': frozenset({'.json', '.tmp'})},  # durations: one ledger per process, staged by durable_text
    'measurement': {'.': frozenset(), '*': frozenset({'.json', '.log'})},  # jobmeasure: receipt and logs per run
    'parts': {'.': frozenset(), '*': frozenset({'.gz', '.tmp'})},  # platformparts: run records per head, durable
    'metrics': {'.': frozenset({'.jsonl'})},  # metrics: one line per event, by event kind
    'walls': {'.': frozenset({'.jsonl'})},  # walls: one line per wall an agent hit
    'consent': {'.': frozenset({'.json'})},  # devhostadmit, forgeenroll, frozen, ops.secretplace: requests
    'units': {'.': frozenset({'.json'})},  # unit_slices: the slice table
    'purge': {'.': frozenset({'.jsonl'})},  # purge: one line per removed directory
    'merge-check': {'.': frozenset({'.jsonl'})},  # purge reads: one classification per parked path
    'prune': {'.': frozenset({'.log'})},  # branchprune --log
    'reclaim': {'.': frozenset({'.log'})},  # reclaimrun
    'reaper': {'.': frozenset({'.log'})},  # shellreaper
}


class UndeclaredOutput(ValueError):
    """The repo does not declare its output root; the message names :data:`OUTPUT_KEY`."""


def _escapes(text: str) -> bool:
    """Whether *text* can leave the root it is joined to, under EITHER platform's spelling.

    ``Path`` is the running platform's flavor, and that is not enough here. MEASURED 2026-09-17:
    ``WindowsPath('/var/log').is_absolute()`` is ``False`` -- a POSIX-absolute base sails through a
    Windows guard and then escapes on the machine where it means something. So both flavors are
    asked, and an upward ``..`` segment is refused too: it escapes without being absolute at all.
    """
    return (
        PurePosixPath(text).is_absolute()
        or PureWindowsPath(text).is_absolute()
        or '..' in PureWindowsPath(text).parts
        or '..' in PurePosixPath(text).parts
    )


def date_parts() -> tuple[str, str, str]:
    """``(yy, mm, dd)`` for THIS PROCESS, in LOCAL time, taken at the call.

    A run that crosses midnight lands under the day it STARTED, because the caller takes this once
    and reuses it -- so the log and the verdict stamped beside it never name two different days.
    Local rather than UTC because the directory is read by a human standing at the box.
    """
    stamp = dt.datetime.now().astimezone()
    return stamp.strftime('%y'), stamp.strftime('%m'), stamp.strftime('%d')


def dated_log(root: Path, name: str, *, base: str, kind: str) -> Path:
    r"""``root/<base>/<yy>/<mm>/<dd>/<kind>/<name>``, its directory created.

    Args:
        root: the checkout whose tree receives the log.
        name: a bare FILENAME. A separator, a drive or a dot-segment is REFUSED rather than
            normalized away: silently taking ``Path(name).name`` would put the file somewhere the
            caller did not ask for and report success.
        base: the repo's own root for dated output, relative to *root*, e.g. ``'output/logs'``.
            NO DEFAULT -- see the module docstring; the four repos in this family give four answers
            and none of them may be handed to the others by omission.
        kind: the leaf directory under the date, e.g. ``'gate'`` or ``'durations'``. NO DEFAULT for
            a smaller reason that points the same way: a kind that arrives by omission makes every
            harness that forgot to name one share a directory, which is the state the sweeper cannot
            act on.

    Returns:
        The dated path, its parent created. The FILE is not created: writing it is the caller's.

    Raises:
        ValueError: *name* is empty, absolute, or carries a path separator; or *base* is absolute or
            empty. An absolute *base* would escape *root*, which makes the ``root/`` in the returned
            path a lie.

    """
    if not base or _escapes(base):
        msg = (
            f'base must be a RELATIVE location inside the checkout and got {base!r}. It is the '
            f'adopting repo\'s own answer to "where does dated output live" -- an absolute one '
            f'escapes the root this was asked about, so the returned path would no longer be a '
            f'statement about that checkout.'
        )
        raise ValueError(msg)
    given = Path(name)
    # Both separators on every OS: a POSIX Path reads ``sub\gate.log`` as ONE part, so the parts
    # count alone let a Windows-spelled path through on Linux and macOS.
    if not name or _escapes(name) or len(given.parts) != 1 or name in {'.', '..'} or '/' in name or '\\' in name:
        msg = (
            f'this takes a NAME, not a path, and got {name!r}. Everything a dated harness writes '
            f'goes under <base>/<yy>/<mm>/<dd>/<kind>/ and there is no exemption: an undated '
            f'artifact cannot be told from one an abandoned lane left behind, and a sweeper cannot '
            f'age out a file with no age. Pass just the filename.'
        )
        raise ValueError(msg)
    dated = dated_base(root, base).joinpath(*date_parts(), kind)
    dated.mkdir(parents=True, exist_ok=True)
    return dated / given.name


def dated_base(root: Path, base: str, *, declared: _storage.Storage | None = None) -> Path:
    """Where *base* (relative to the checkout *root*) lives: under the BOUND ``output`` kind when it is output.

    A *base* inside the in-tree ``output`` default (``output/logs``) moves with the ``output`` storage kind when this
    machine binds it (``[storage.roots] output``, :mod:`dev_lab.dev.storage`): the bound root of the repository's
    MAIN checkout, shared by its worktrees. Unbound, it is ``root/base`` -- the tree's own, as before. Any other
    *base* is ``root/base``.
    """
    parts = Path(base).parts
    declared = _storage.declared() if declared is None else declared
    if parts and parts[0] == _storage.KINDS['output'] and 'output' in declared.roots:
        return output_path(root, *parts[1:], declared=declared)
    return root.joinpath(*parts)


def declared_output(root: Path) -> str:
    """*root*'s ``[tool.dev_lab.parts] output``, relative to *root* (e.g. ``'output/logs'``).

    Raises:
        UndeclaredOutput: no pyproject, or no non-empty string under the key.

    """
    pyproject = root / 'pyproject.toml'
    text = pyproject.read_text(encoding='utf-8') if pyproject.is_file() else ''
    value = declared_in(text, 'parts').get('output')
    if not isinstance(value, str) or not value:
        msg = f'{root / "pyproject.toml"} must declare {OUTPUT_KEY} as a non-empty string, e.g. output = "output/logs"'
        raise UndeclaredOutput(msg)
    return value


def output_dir(root: Path, kind: str) -> Path:
    """Today's ``<declared output>/<yy>/<mm>/<dd>/<kind>/`` under *root*, created.

    Raises:
        UndeclaredOutput: *root* declares no output root.

    """
    return dated_log(root, kind, base=declared_output(root), kind=kind).parent
