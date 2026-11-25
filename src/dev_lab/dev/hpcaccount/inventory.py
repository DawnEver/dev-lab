"""``look --account <user> inventory <path>`` -- what a directory of an account holds, before it is archived or cleaned.

User ruling 2026-11-25: an account is cleaned completely, its results of record archived first (``hpcaccount
archive``). Deciding which directory needs an archive and which may simply go needed two reads no door made: how
big and how recently touched each entry is, and whether every git checkout in it is PROVEN pushed. This is that
read, ONE fixed shell line (:func:`command`) whose only input is a home-relative path of names, so it cannot write:

* per entry of ``~/<path>`` (dot entries included): its files (every inode a file quota counts), bytes and newest
  modification -- one ``find -xdev`` walk each;
* per git checkout found up to :data:`DEPTH` levels below ``~/<path>`` (a ``.git`` directory or a worktree's
  ``.git`` file): its fetch remotes, ``status --porcelain --ignored`` (``--no-optional-locks``: the index is never
  refreshed), the count and the first :data:`SHOWN` commits of ``git log --branches HEAD --not --remotes``, and its
  stash entries.

:func:`parse` reads the tagged lines; :class:`Checkout.reasons` is the verdict. A checkout is ``pushed`` only when it
has a remote, nothing changed or untracked, no commit on no remote, no stash, and git answered every question; any
other answer -- a git that could not count -- is NOT PUSHED, never a guess. What git IGNORES (an ``output/`` that
may hold results, a ``.venv`` that does not) is listed for a person to judge; it does not decide the verdict.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final

__all__ = ['DEPTH', 'SHOWN', 'Checkout', 'Entry', 'Inventory', 'command', 'parse', 'rows']

#: How many levels below the inventoried path a git checkout is looked for (``src/<repo>`` is two).
DEPTH: Final = 4
#: How many changed paths, unpushed commits and ignored paths of one checkout are shown.
SHOWN: Final = 20
#: An ``E`` row's fields: files, bytes, newest change and the entry's path.
_E_FIELDS: Final = 4
#: An ``R`` row's fields: the remote's name and its url.
_R_FIELDS: Final = 2
#: One binary unit step of :func:`_size`.
_KIB: Final = 1024

_GIT_STEPS: Final = (
    'd=${g%/.git}; printf "G\\t%s\\n" "$d"; '
    'git -C "$d" remote -v 2>&1 | awk \'$3 == "(fetch)" { printf "R\\t%s\\t%s\\n", $1, $2 }\'; '
    's=$(git -C "$d" --no-optional-locks status --porcelain --ignored 2>&1); '
    "printf 'S\\t%s\\n' \"$(printf '%s\\n' \"$s\" | grep -v '^!! ' | grep -c .)\"; "
    f"printf '%s\\n' \"$s\" | grep -v '^!! ' | grep . | head -n {SHOWN} | awk '{{ print \"s\\t\" $0 }}'; "
    f"printf '%s\\n' \"$s\" | grep '^!! ' | head -n {SHOWN} | awk '{{ print \"I\\t\" substr($0, 4) }}'; "
    'printf "U\\t%s\\n" "$(git -C "$d" rev-list --count --branches HEAD --not --remotes 2>&1 | head -n 1)"; '
    f'git -C "$d" log --branches HEAD --not --remotes --format=\'%h %D %s\' 2>/dev/null | head -n {SHOWN} '
    '| awk \'{ print "u\\t" $0 }\'; '
    'printf "T\\t%s\\n" "$(git -C "$d" stash list 2>/dev/null | wc -l | tr -d " ")"'
)


def command(path: str) -> str:
    """The fixed, read-only shell line that inventories ``~/<path>`` (the caller has judged *path*'s shape)."""
    walk = (
        'find "$e" -xdev -printf \'%T@ %s\\n\' 2>/dev/null | awk -v e="$e" '
        "'BEGIN { n = 0; b = 0; m = 0 } { n++; b += $2; if ($1 > m) m = $1 } "
        'END { printf "E\\t%.0f\\t%.0f\\t%.0f\\t%s\\n", n, b, m, e }\''
    )
    return (
        f'p="$HOME"/{shlex.quote(path)}; [ -d "$p" ] || {{ printf "A\\t%s\\n" "$p"; exit 0; }}; '
        'printf "P\\t%s\\n" "$p"; '
        'for e in "$p"/* "$p"/.[!.]* "$p"/..?*; do { [ -e "$e" ] || [ -L "$e" ]; } || continue; '
        f'{walk}; done; '
        f'find "$p" -xdev -maxdepth {DEPTH} -name .git -prune -print 2>/dev/null | sort | '
        f'while IFS= read -r g; do {_GIT_STEPS}; done'
    )


@dataclass(frozen=True)
class Entry:
    """One entry of the inventoried path: its files, bytes and newest modification (epoch seconds)."""

    path: str
    files: int
    bytes: int
    newest: int


@dataclass
class Checkout:
    """One git checkout and what git answered about it."""

    path: str
    remotes: list[tuple[str, str]] = field(default_factory=list)
    changed: int | None = None
    changes: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    unpushed: str = ''
    commits: list[str] = field(default_factory=list)
    stash: str = ''

    def reasons(self) -> list[str]:
        """Why this checkout is NOT proven pushed; empty: it is."""
        why = []
        if self.changed is None:
            why.append('git status did not answer')
        elif self.changed:
            why.append(f'{self.changed} changed or untracked path(s)')
        if not self.unpushed.isdigit():
            why.append(f'git could not count unpushed commits: {self.unpushed or "no answer"}')
        elif int(self.unpushed):
            why.append(f'{self.unpushed} commit(s) on no remote')
        if not self.stash.isdigit():
            why.append('git stash did not answer')
        elif int(self.stash):
            why.append(f'{self.stash} stash entr(y/ies)')
        if not self.remotes:
            why.append('no remote')
        return why


@dataclass
class Inventory:
    """What :func:`command` printed: the path (``absent`` when it does not exist), its entries and checkouts."""

    path: str = ''
    absent: bool = False
    entries: list[Entry] = field(default_factory=list)
    checkouts: list[Checkout] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)


def _line(found: Inventory, tag: str, rest: list[str]) -> None:
    last = found.checkouts[-1] if found.checkouts else None
    if tag in {'P', 'A'}:
        found.path, found.absent = rest[0], tag == 'A'
    elif tag == 'E' and len(rest) == _E_FIELDS and all(v.isdigit() for v in rest[:3]):
        found.entries.append(Entry(rest[3], int(rest[0]), int(rest[1]), int(rest[2])))
    elif tag == 'G':
        found.checkouts.append(Checkout(rest[0]))
    elif last is None:
        found.unread.append('\t'.join([tag, *rest]))
    elif tag == 'R' and len(rest) == _R_FIELDS:
        last.remotes.append((rest[0], rest[1]))
    elif tag == 'S':
        last.changed = int(rest[0]) if rest[0].isdigit() else None
    else:
        target = {'s': last.changes, 'I': last.ignored, 'u': last.commits}.get(tag)
        if target is not None:
            target.append('\t'.join(rest))
        elif tag == 'U':
            last.unpushed = '\t'.join(rest).strip()
        elif tag == 'T':
            last.stash = '\t'.join(rest).strip()
        else:
            found.unread.append('\t'.join([tag, *rest]))


def parse(text: str) -> Inventory:
    """The tagged lines of :func:`command` as an :class:`Inventory`; a line it cannot read is kept in ``unread``."""
    found = Inventory()
    for raw in text.splitlines():
        tag, _, rest = raw.partition('\t')
        if raw.strip():
            _line(found, tag, rest.split('\t') if tag != 's' else [rest])
    return found


def _size(count: int) -> str:
    value = float(count)
    for unit in ('B', 'K', 'M', 'G'):
        if value < _KIB:
            return f'{value:.1f}{unit}' if unit != 'B' else f'{count}B'
        value /= _KIB
    return f'{value:.1f}T'


def _when(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime('%Y-%m-%d %H:%M') if epoch else '-'


def rows(text: str) -> list[str]:
    """The inventory as lines a person reads: entries by files, then each checkout's verdict and what decided it."""
    found = parse(text)
    if found.absent:
        return [f'inventory: {found.path} does not exist']
    entries = sorted(found.entries, key=lambda e: (-e.files, e.path))
    total_files, total_bytes = sum(e.files for e in entries), sum(e.bytes for e in entries)
    out = [
        f'inventory: {found.path} -- {len(entries)} entr(y/ies), {total_files} files, {_size(total_bytes)}',
        f'  {"files":>9}  {"size":>8}  {"newest (UTC)":<16}  entry',
        *(f'  {e.files:>9}  {_size(e.bytes):>8}  {_when(e.newest):<16}  {e.path}' for e in entries),
        f'checkouts ({len(found.checkouts)}, searched {DEPTH} levels deep):',
    ]
    for checkout in found.checkouts:
        remotes = ', '.join(f'{name} {url}' for name, url in checkout.remotes)
        why = checkout.reasons()
        out.append(f'  {checkout.path}: ' + (f'NOT PUSHED -- {"; ".join(why)}' if why else f'pushed ({remotes})'))
        out.extend(f'    {line}' for line in checkout.changes)
        out.extend(f'    unpushed {line}' for line in checkout.commits)
        if checkout.ignored:
            out.append(f'    ignored (judge before cleaning): {", ".join(checkout.ignored)}')
    out.extend(f'inventory: unread line {line!r}' for line in found.unread)
    return out
