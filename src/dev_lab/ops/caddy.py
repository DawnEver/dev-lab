"""``[ops.caddy]``: the forge's Caddy allowlist as configuration, rewritten by the install door (2026-11-09).

The campus-only allowlist used to be a hand-edited ``@<name> remote_ip ...`` line of the Caddyfile, which only root
could change -- and after the lockdown no account holds root. So the allowed addresses are declared once, under
``[ops.caddy] allow``, and :func:`allowlisted` rewrites EVERY ``remote_ip`` matcher of the declared ``sites`` (all
sites when none is named) to that list, leaving every other byte alone. A Caddyfile with no such matcher, a named
site that is absent, or a value that is not an IP address or CIDR is refused, never guessed at: the value lands in a
file root's web server parses, so it is checked by :mod:`ipaddress`, not by shape.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ['Caddy', 'allowlisted', 'install_caddy']


@dataclass(frozen=True)
class Caddy:
    """The forge's Caddy allowlist (:mod:`dev_lab.ops.caddy`).

    Every ``remote_ip`` matcher of ``sites`` (all, when empty) in ``file`` admits exactly ``allow`` (IPs or CIDRs).
    """

    allow: tuple[str, ...]
    file: str = '/etc/caddy/Caddyfile'
    sites: tuple[str, ...] = ()


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


def install_caddy(caddy: Caddy | None, root: Path, rendered: dict[str, str]) -> list[str]:
    """The install step: add the allowlisted Caddyfile to *rendered*, its old text kept beside it when it changes.

    Returns the reload step when the file changed; nothing when ``[ops.caddy]`` is undeclared or nothing moved.
    """
    if caddy is None:
        return []
    live = root / Path(caddy.file).relative_to(Path(caddy.file).anchor)
    if not live.is_file():
        msg = f'[ops.caddy] file {caddy.file} does not exist'
        raise ValueError(msg)
    old = live.read_text(encoding='utf-8')
    new = allowlisted(old, caddy.allow, sites=caddy.sites)
    rendered[live.relative_to(root).as_posix()] = new
    if new == old:
        return []
    live.with_name(f'{live.name}.bak-dev-lab').write_text(old, encoding='utf-8', newline='\n')
    return [f'caddy validate --config {caddy.file} && systemctl reload caddy']
