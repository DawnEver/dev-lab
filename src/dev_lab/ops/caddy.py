"""``[ops.caddy]``: the forge's Caddy allowlist as configuration, rewritten by the install door (2026-11-09).

The campus-only allowlist used to be a hand-edited ``@<name> remote_ip ...`` line of the Caddyfile, which only root
could change -- and after the lockdown no account holds root. So the allowed addresses are declared once, under
``[ops.caddy] allow``, and :func:`allowlisted` rewrites EVERY ``remote_ip`` matcher of the declared ``sites`` (all
sites when none is named) to that list, leaving every other byte alone. A Caddyfile with no such matcher, a named
site that is absent, or a value that is not an IP address or CIDR is refused, never guessed at: the value lands in a
file root's web server parses, so it is checked by :mod:`ipaddress`, not by shape.

``[ops.status]`` (:class:`Status`, 2026-11-13) adds ONE managed route to its declared site: the supervisor's status
card (:mod:`dev_lab.supervise.card`) at ``path``, served read-only from the card's own directory to the same
``[ops.caddy] allow`` list, matched before every other handler of the site (:func:`status_routed`). Undeclared, the
route is removed.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Final

__all__ = ['Caddy', 'Status', 'allowlisted', 'install_caddy', 'status_routed', 'status_unrouted']


@dataclass(frozen=True)
class Caddy:
    """The forge's Caddy allowlist (:mod:`dev_lab.ops.caddy`).

    Every ``remote_ip`` matcher of ``sites`` (all, when empty) in ``file`` admits exactly ``allow`` (IPs or CIDRs).
    """

    allow: tuple[str, ...]
    file: str = '/etc/caddy/Caddyfile'
    sites: tuple[str, ...] = ()


#: A path that lands in the Caddyfile: plain characters only, so it cannot widen the config it is written into.
_PLAIN: Final = re.compile(r'/[A-Za-z0-9/_.-]+')


@dataclass(frozen=True)
class Status:
    """The host's status card (:mod:`dev_lab.supervise.card`): where the supervisor writes it, where Caddy serves it.

    ``file`` is the card (absolute; its directory holds nothing else -- it is what Caddy's ``root`` names); ``site``
    the Caddyfile site that serves it at ``path``, to the ``[ops.caddy] allow`` list only.
    """

    file: str
    site: str
    path: str = '/dev-lab/status.json'

    def __post_init__(self) -> None:
        """Refuse a value that is not a plain absolute path: each lands in a file root's web server parses."""
        for key, value in (('file', self.file), ('path', self.path)):
            if not _PLAIN.fullmatch(value) or '..' in value:
                msg = f'[ops.status] {key} must be an absolute plain path, got {value!r}'
                raise ValueError(msg)

    def flags(self, audit: str) -> list[str]:
        """The supervisor's ``--card`` flags: the card, and the auto-upgrade *audit* whose last line it quotes."""
        return ['--card', self.file, '--card-audit', audit]

    def directory_step(self, owner: str) -> str:
        """The step making the card's own directory: world-readable for Caddy, *owner*'s (empty: root) to write."""
        return f'install -d -m 0755 -o {owner or "root"} {PurePosixPath(self.file).parent}'


_MATCHER: Final = re.compile(r'^(?P<head>\s*@\S+\s+remote_ip)\s+(?P<list>[^\n{}#]+?)\s*$')
_SITE: Final = re.compile(r'^(?P<names>[^\s{#][^{#\n]*?)\s*\{\s*$')


def _checked(allow: Sequence[str]) -> str:
    if not allow:
        msg = '[ops.caddy] allow is empty: a campus-only site would admit nobody'
        raise ValueError(msg)
    for value in allow:
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            msg = f'[ops.caddy] allow: {value!r} is not an address or CIDR'
            raise ValueError(msg) from None
    return ' '.join(allow)


def allowlisted(text: str, allow: Sequence[str], *, sites: Sequence[str] = ()) -> str:
    """*text* (a Caddyfile) with every ``remote_ip`` matcher of *sites* (all, when empty) set to *allow*.

    Raises:
        ValueError: *allow* is empty or holds a non-address, a named site is absent, or no matcher was found.

    """
    wanted = _checked(allow)
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    depth = 0
    site: tuple[str, ...] = ()
    seen: set[str] = set()
    rewritten = 0
    for raw in lines:
        line = raw  # a matcher line is rewritten in place
        if depth == 0 and (top := _SITE.match(line.rstrip('\n'))):
            site = tuple(name.strip() for name in top['names'].replace(',', ' ').split())
            seen.update(site)
        inside = not sites or any(name in sites for name in site)
        if depth > 0 and inside and (matcher := _MATCHER.match(line.rstrip('\n'))):
            newline = '\n' if line.endswith('\n') else ''
            line = f'{matcher["head"]} {wanted}{newline}'
            rewritten += 1
        depth += line.count('{') - line.count('}')
        if depth == 0:
            site = ()
        out.append(line)
    if missing := [name for name in sites if name not in seen]:
        msg = f'[ops.caddy] sites: {missing} is not a site of the Caddyfile'
        raise ValueError(msg)
    if not rewritten:
        msg = 'the Caddyfile has no `@<name> remote_ip ...` matcher to rewrite; declare the allowlist by hand once'
        raise ValueError(msg)
    return ''.join(out)


#: The lines that open and close the managed status route; everything between them is rendered, never edited.
_BEGIN: Final = '\t# dev-lab status card -- rendered by dev_lab.ops ([ops.status]); edits are overwritten\n'
_END: Final = '\t# end dev-lab status card\n'


def status_routed(text: str, *, site: str, path: str, file: str, allow: Sequence[str]) -> str:
    """*text* (a Caddyfile) with the managed status route as the first block of *site*; any older route dropped.

    Raises:
        ValueError: *site* is not a site of *text*, or *allow* is empty or holds a non-address.

    """
    card = PurePosixPath(file)
    route = (
        f'{_BEGIN}\t@dev_lab_status {{\n\t\tpath {path}\n\t\tremote_ip {_checked(allow)}\n\t}}\n'
        f'\thandle @dev_lab_status {{\n\t\troot * {card.parent}\n\t\trewrite * /{card.name}\n'
        f'\t\theader Cache-Control no-store\n\t\tfile_server\n\t}}\n{_END}'
    )
    out: list[str] = []
    depth, placed = 0, False
    for line in status_unrouted(text).splitlines(keepends=True):
        out.append(line)
        top = _SITE.match(line.rstrip('\n')) if depth == 0 else None
        if top and not placed and site in top['names'].replace(',', ' ').split():
            out.append(route)
            placed = True
        depth += line.count('{') - line.count('}')
    if not placed:
        msg = f'[ops.status] site: {site!r} is not a site of the Caddyfile'
        raise ValueError(msg)
    return ''.join(out)


def status_unrouted(text: str) -> str:
    """*text* without the managed status route (unchanged when it holds none)."""
    start = text.find(_BEGIN)
    end = text.find(_END)
    return text if start < 0 or end < start else text[:start] + text[end + len(_END) :]


def install_caddy(caddy: Caddy | None, root: Path, rendered: dict[str, str], status: Status | None = None) -> list[str]:
    """The install step: add the allowlisted Caddyfile to *rendered*, its old text kept beside it when it changes.

    Returns the reload step whenever the file Caddy would load is not the one it last loaded; nothing when
    ``[ops.caddy]`` is undeclared or the live config is the file.

    WHY A STAMP, NOT "THE FILE CHANGED" (2026-11-10): the reload is a next step an operator runs, and one write's
    reload was never run -- the next install found the file already right, said ``unchanged`` and named nothing,
    while the running Caddy still served the old allowlist. An unchanged FILE is not a live CONFIG. So the reload
    step records the digest it loaded in ``<file>.reloaded-sha256``, and install names the reload until that stamp
    matches the file -- which also catches a file placed by ``config apply`` or a hand edit that never reloaded.
    """
    if caddy is None:
        return []
    live = root / Path(caddy.file).relative_to(Path(caddy.file).anchor)
    if not live.is_file():
        msg = f'[ops.caddy] file {caddy.file} does not exist'
        raise ValueError(msg)
    old = live.read_text(encoding='utf-8')
    new = allowlisted(old, caddy.allow, sites=caddy.sites)
    if status is None:
        new = status_unrouted(new)
    else:
        new = status_routed(new, site=status.site, path=status.path, file=status.file, allow=caddy.allow)
    rendered[live.relative_to(root).as_posix()] = new
    if new != old:
        live.with_name(f'{live.name}.bak-dev-lab').write_text(old, encoding='utf-8', newline='\n')
    elif _reloaded(live) == hashlib.sha256(live.read_bytes()).hexdigest():
        return []
    stamp = f'{caddy.file}{_STAMP}'
    return [f'caddy validate --config {caddy.file} && systemctl reload caddy && sha256sum {caddy.file} > {stamp}']


#: Beside the Caddyfile: ``sha256sum``'s line for the file the last reload loaded.
_STAMP: Final = '.reloaded-sha256'


def _reloaded(live: Path) -> str | None:
    """The digest the last reload stamped beside *live*, or None when no reload ever stamped one."""
    stamp = live.with_name(f'{live.name}{_STAMP}')
    if not stamp.is_file():
        return None
    words = stamp.read_text(encoding='utf-8').split()
    return words[0] if words else None
