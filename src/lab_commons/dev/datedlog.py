"""ONE CALENDAR for everything a dev harness writes -- ``<base>/<yy>/<mm>/<dd>/<kind>/<name>``.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/_dated.py``, where FOUR harnesses had
implemented the same layout independently (a gate runner, a pre-push gate, a measurement harness and
an output-hygiene sweeper). Four calendars that can drift apart, and four docstrings asserting the
same layout, is the duplication this module ends.

**THE BASE IS THE REPO'S ANSWER AND HAS NO DEFAULT**, and that is a MEASUREMENT rather than caution.
motronics writes under ``output/logs/`` because a user directive said so on 2026-09-03; this very
package writes its own verify log to ``.verify/`` (:data:`lab_commons.dev.verify.LOG_DIRECTORY`) and
the two labs have no dated tree at all. So the family holds four answers to "where", and a default
here would hand any of the other three motronics' directive while looking like a shared convention.
What IS universal is the partition -- a date taken once, a kind beneath it, and a NAME that may not
escape either.

WHAT THIS IS NOT. It does not name a verdict, address a tree, or stamp a log: a log's CONTENT and
its citation belong to :mod:`lab_commons.dev.logref`, and this answers only where the file sits.

A NAME, NEVER A PATH, AND THERE IS NO EXEMPTION. The version this was migrated from had carried two
escape hatches and had them removed on 2026-09-08 after neither checked the thing it excused: an
``is_absolute()`` branch excused every path merely spelled in full, and a ``'logs' in parts`` branch
matched the segment anywhere, so ``logs/x.log`` passed while being no more dated than a bare name.
They are not reinstated here. An undated artefact cannot be told from one an abandoned lane left
behind, and a sweeper cannot age out a file with no age.
"""

from __future__ import annotations

import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = ['date_parts', 'dated_log']


def _escapes(text: str) -> bool:
    """Whether *text* can leave the root it is joined to, under EITHER platform's spelling.

    ``Path`` is the running platform's flavour, and that is not enough here. MEASURED 2026-09-17:
    ``WindowsPath('/var/log').is_absolute()`` is ``False`` -- a POSIX-absolute base sails through a
    Windows guard and then escapes on the machine where it means something. So both flavours are
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
    stamp = datetime.datetime.now().astimezone()
    return stamp.strftime('%y'), stamp.strftime('%m'), stamp.strftime('%d')


def dated_log(root: Path, name: str, *, base: str, kind: str) -> Path:
    r"""``root/<base>/<yy>/<mm>/<dd>/<kind>/<name>``, its directory created.

    Args:
        root: the checkout whose tree receives the log.
        name: a bare FILENAME. A separator, a drive or a dot-segment is REFUSED rather than
            normalised away: silently taking ``Path(name).name`` would put the file somewhere the
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
    if not name or _escapes(name) or len(given.parts) != 1 or name in {'.', '..'}:
        msg = (
            f'this takes a NAME, not a path, and got {name!r}. Everything a dated harness writes '
            f'goes under <base>/<yy>/<mm>/<dd>/<kind>/ and there is no exemption: an undated '
            f'artefact cannot be told from one an abandoned lane left behind, and a sweeper cannot '
            f'age out a file with no age. Pass just the filename.'
        )
        raise ValueError(msg)
    dated = root.joinpath(*Path(base).parts, *date_parts(), kind)
    dated.mkdir(parents=True, exist_ok=True)
    return dated / given.name
