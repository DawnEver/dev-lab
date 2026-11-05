"""Clone-URL naming for the ``git_mirror`` dumper: one ``<host>_<owner>_<repo>`` name and its host per URL."""

from __future__ import annotations

import re

__all__ = ['mirror_host', 'mirror_name']

#: ``[user@]host:path``; a one-letter host is a Windows drive, not a forge.
_SCP = re.compile(r'^(?:[^@/\\]+@)?(?P<host>[^:/\\]{2,}):(?P<path>.+)$')


def mirror_name(url: str) -> str:
    """``<host>_<owner>_<repo>`` of a clone URL (scheme, credentials, port, ``.git`` dropped); a path keeps parts."""
    return '_'.join(_mirror_parts(url))


def mirror_host(url: str) -> str:
    """The forge host of a clone URL as :func:`mirror_name` spells it: the key of ``mirror_tokens``."""
    return _mirror_parts(url)[0]


def _mirror_parts(url: str) -> list[str]:
    if '://' in url:
        authority, _, path = url.partition('://')[2].partition('/')
        rest = f'{authority.rpartition("@")[2].partition(":")[0]}/{path}'
    elif scp := _SCP.match(url):
        rest = f'{scp["host"]}/{scp["path"]}'
    else:
        rest = url
    parts = [part for part in re.split(r'[/\\]+', rest.strip('/\\').removesuffix('.git')) if part]
    return [re.sub(r'[^A-Za-z0-9._-]', '-', part) for part in parts]
