"""THE ACCOUNT HALF OF ``hpcaccount salvage``: two fixed, read-only shell lines and the readers of what they print.

An account is cleaned completely (user ruling 2026-11-25), and before it is, every commit on no remote and every
uncommitted change in its checkouts comes back to the workstation. The account sits near its file quota, so NOTHING
is written there: each line prints, the Runner carries the print home, base64 where it is data.

* :func:`plan_command` -- every checkout under ``~/<path>`` (:data:`~dev_lab.dev.hpcaccount.inventory.FOUND`, the
  inventory's own discovery) with its remotes, branch, HEAD, shared git directory, stash entries, the count of
  :data:`~dev_lab.dev.hpcaccount.inventory.UNPUSHED` (the inventory's own "on no remote") and the bundle's bytes,
  the tracked change (``git diff HEAD --binary``: paths and bytes) and every untracked, non-ignored file with its
  size. A checkout git cannot read is an ``X`` line carrying git's own words.
* :func:`data_command` -- ONE checkout's data, each a section of base64 lines: ``bundle`` (``git bundle create -``
  of :data:`~dev_lab.dev.hpcaccount.inventory.UNPUSHED`), ``diff`` and ``untracked`` (a tar of the untracked files
  no larger than the carried limit), each closed by its producer's exit status.

Both are POSIX ``sh`` with GNU ``find``/``stat``/``tar``/``base64``, which every cluster login host and Git for
Windows carry. Every data line is tagged, so a login banner or a tool's stray stderr can never be read as data.
"""

from __future__ import annotations

import base64
import binascii
import shlex
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Final

from dev_lab.dev.hpcaccount.inventory import FOUND, UNPUSHED, opened

__all__ = ['SECTIONS', 'Checkout', 'Plan', 'Untracked', 'data_command', 'parse', 'plan_command', 'sections']

#: The data sections of one checkout, in the order they are produced.
SECTIONS: Final = ('bundle', 'diff', 'untracked')
#: What ``stat %F`` names a file a tar carries; a directory is a nested checkout, found on its own.
_CARRIED_KINDS: Final = frozenset({'regular file', 'regular empty file', 'symbolic link'})
#: What ``stat %F`` names a symlink: carried whatever its target's size.
_LINK: Final = 'symbolic link'
#: An ``N`` row's fields: kind, bytes and the path.
_N_FIELDS: Final = 3

_RECORD: Final = (
    'd=${g%/.git}; r=${d#"$h"/}; [ "$d" = "$h" ] && r=.; '
    'if ! e=$(git -C "$d" rev-parse --git-dir 2>&1); then '
    'printf "X\\t%s\\t%s\\n" "$r" "$(printf "%s\\n" "$e" | head -n 1)"; continue; fi; '
    'printf "G\\t%s\\n" "$r"; '
    'git -C "$d" remote -v 2>/dev/null | awk \'$3 == "(fetch)" { printf "R\\t%s\\t%s\\n", $1, $2 }\'; '
    'printf "B\\t%s\\n" "$(git -C "$d" symbolic-ref -q --short HEAD)"; '
    'printf "H\\t%s\\n" "$(git -C "$d" rev-parse -q --verify HEAD)"; '
    'printf "C\\t%s\\n" "$(cd "$d" && cd "$(git rev-parse --git-common-dir)" && pwd -P)"; '
    'printf "T\\t%s\\n" "$(git -C "$d" stash list 2>/dev/null | wc -l | tr -d " ")"; '
    f'u=$(git -C "$d" rev-list --count {UNPUSHED} 2>&1 | head -n 1); printf "U\\t%s\\n" "$u"; '
    'case "$u" in ""|0|*[!0-9]*) printf "L\\t0\\n";; '
    f'*) printf "L\\t%s\\n" "$(git -C "$d" bundle create - {UNPUSHED} 2>/dev/null | wc -c | tr -d " ")";; esac; '
    'printf "D\\t%s\\t%s\\n" "$(git -C "$d" --no-optional-locks diff HEAD --name-only 2>/dev/null | grep -c .)" '
    '"$(git -C "$d" --no-optional-locks diff HEAD --binary 2>/dev/null | wc -c | tr -d " ")"; '
    '(cd "$d" && git ls-files -z --others --exclude-standard | xargs -0 -r stat --printf "N\\t%F\\t%s\\t%n\\n" --) '
    '2>/dev/null'
)


def plan_command(path: str) -> str:
    """The fixed, read-only line that lists every checkout under ``~/<path>`` and what it holds of its own."""
    return f'{opened(path)}{FOUND} | while IFS= read -r g; do {_RECORD}; done'


def data_command(checkout: str, carried: int) -> str:
    """The fixed, read-only line that prints *checkout*'s (home-relative) bundle, diff and untracked files.

    Untracked files of at most *carried* bytes ride in the tar; a larger one is listed by the plan, never carried.
    """
    where = '"$h"' if checkout == '.' else f'"$h"/{shlex.quote(checkout)}'
    pick = (
        f'for f do if [ -L "$f" ] || {{ [ -f "$f" ] && [ "$(wc -c < "$f")" -le {int(carried)} ]; }}; '
        'then printf "./%s\\0" "$f"; fi; done'
    )
    return (
        f'h=$(cd "$HOME" && pwd -P); cd {where} 2>/dev/null || {{ printf "X\\t%s\\tno such checkout\\n" '
        f'{shlex.quote(checkout)}; exit 0; }}; exec 4>&1; '
        's() { n=$1; shift; printf ">\\t%s\\n" "$n"; '
        'c=$( { { "$@" 2>/dev/null; echo $? >&3; } | base64 | awk \'{ print "d\\t" $0 }\' >&4; } 3>&1 ); '
        'printf "<\\t%s\\t%s\\n" "$n" "$c"; }; '
        f'u=$(git rev-list --count {UNPUSHED} 2>/dev/null); '
        f'case "$u" in ""|0|*[!0-9]*) ;; *) s bundle git bundle create - {UNPUSHED};; esac; '
        'git rev-parse -q --verify HEAD >/dev/null && s diff git --no-optional-locks diff HEAD --binary; '
        f't() {{ git ls-files -z --others --exclude-standard | xargs -0 -r sh -c {shlex.quote(pick)} sh '
        '| tar --null --no-recursion -T - -cf -; }; s untracked t'
    )


@dataclass(frozen=True)
class Untracked:
    """One untracked, non-ignored file: its path in the checkout, its bytes and what ``stat`` called it."""

    path: str
    bytes: int
    kind: str


@dataclass
class Checkout:
    """One checkout as the plan line printed it."""

    path: str
    remotes: list[tuple[str, str]] = field(default_factory=list)
    branch: str = ''
    head: str = ''
    common: str = ''
    stash: str = ''
    unpushed: str = ''
    bundle_bytes: int = 0
    changed: int = 0
    diff_bytes: int = 0
    untracked: list[Untracked] = field(default_factory=list)

    @property
    def origin(self) -> str:
        """The ``origin`` fetch url, else the first remote's, else ``''``."""
        urls = dict(self.remotes)
        return urls.get('origin') or (self.remotes[0][1] if self.remotes else '')

    def unread(self) -> str:
        """Why git's answers about this checkout cannot be trusted (``''``: they can)."""
        if not self.unpushed.isdigit():
            return f'git could not count its commits on no remote: {self.unpushed or "no answer"}'
        if int(self.unpushed) and not self.bundle_bytes:
            return f'git counts {self.unpushed} commit(s) on no remote but could not bundle them'
        return ''

    def carried(self, limit: int) -> list[Untracked]:
        """The untracked files the tar carries: a regular file of at most *limit* bytes, or a symlink."""
        return [u for u in self.untracked if u.kind in _CARRIED_KINDS and (u.kind == _LINK or u.bytes <= limit)]

    def listed(self, limit: int) -> list[Untracked]:
        """The untracked files too large to carry: listed by name and size only."""
        return [u for u in self.untracked if u.kind in _CARRIED_KINDS and u.kind != _LINK and u.bytes > limit]


@dataclass
class Plan:
    """What :func:`plan_command` printed: the path (``absent`` when missing), its checkouts and the unreadable ones."""

    path: str = ''
    absent: bool = False
    checkouts: list[Checkout] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)


def _safe(path: str) -> bool:
    """A home-relative path that stays under the home (no root, no ``..``)."""
    parts = PurePosixPath(path).parts
    return path == '.' or (bool(parts) and not PurePosixPath(path).is_absolute() and '..' not in parts)


def _number(text: str) -> int:
    return int(text) if text.strip().isdigit() else 0


def _row(last: Checkout, tag: str, rest: list[str]) -> bool:
    """Fold one per-checkout row into *last*; ``False`` when it is not one."""
    single = {'B': 'branch', 'H': 'head', 'C': 'common', 'T': 'stash', 'U': 'unpushed'}
    if tag in single:
        setattr(last, single[tag], '\t'.join(rest).strip())
    elif tag == 'R' and len(rest) == 2:  # noqa: PLR2004 -- a remote's name and its url
        last.remotes.append((rest[0], rest[1]))
    elif tag == 'L':
        last.bundle_bytes = _number(rest[0])
    elif tag == 'D' and len(rest) == 2:  # noqa: PLR2004 -- changed paths and the diff's bytes
        last.changed, last.diff_bytes = _number(rest[0]), _number(rest[1])
    elif tag == 'N' and len(rest) >= _N_FIELDS and rest[1].isdigit():
        last.untracked.append(Untracked('\t'.join(rest[2:]), int(rest[1]), rest[0]))
    else:
        return False
    return True


def parse(text: str) -> Plan:
    """The tagged lines of :func:`plan_command` as a :class:`Plan`; a line it cannot read is kept in ``unread``."""
    found = Plan()
    for raw in text.splitlines():
        tag, _, tail = raw.partition('\t')
        rest = tail.split('\t')
        last = found.checkouts[-1] if found.checkouts else None
        if tag in {'P', 'A'}:
            found.path, found.absent = tail, tag == 'A'
        elif tag == 'G' and _safe(tail):
            found.checkouts.append(Checkout(tail))
        elif tag == 'X' and len(rest) >= 2 and _safe(rest[0]):  # noqa: PLR2004 -- the checkout and git's words
            found.refused.append((rest[0], '\t'.join(rest[1:])))
        elif (last is None or not _row(last, tag, rest)) and raw.strip():
            found.unread.append(raw)
    return found


def sections(text: str) -> tuple[dict[str, bytes], dict[str, str], list[str]]:
    """The data sections :func:`data_command` printed: ``(bytes per section, exit status per section, refusals)``.

    A section whose base64 does not decode is refused by name; lines outside a section are ignored (a banner).
    """
    data: dict[str, list[str]] = {}
    status: dict[str, str] = {}
    refused: list[str] = []
    current = ''
    for raw in text.splitlines():
        tag, _, tail = raw.partition('\t')
        if tag == '>' and tail in SECTIONS:
            current = tail
            data[current] = []
        elif tag == 'd' and current:
            data[current].append(tail.strip())
        elif tag == '<' and current:
            status[current] = tail.partition('\t')[2].strip()
            current = ''
        elif tag == 'X':
            refused.append(tail.replace('\t', ': '))
    decoded = {}
    for name, lines in data.items():
        try:
            decoded[name] = base64.b64decode(''.join(lines), validate=True)
        except binascii.Error as bad:
            refused.append(f'{name}: the account sent base64 that does not decode ({bad})')
    return decoded, status, refused
