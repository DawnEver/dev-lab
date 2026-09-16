"""The environment a verdict was earned IN, keyed so the verdict can name it.

A content address answers "which code". It cannot answer "in what", and the two are equally part of
a verdict: this family floats its dependencies by directive and keeps no committed lock, so the set
of versions that actually ran is a fact about a MACHINE at a MOMENT. A verdict earned under one
resolution and cited under another describes a run nobody performed -- so the key travels IN the
verdict, and a difference in it means the verdict does not exist rather than that it is stale.

WHY THE KEY TAKES A MANIFEST RATHER THAN READING ONE. Two functions that each read the environment
can describe two different environments; a manifest and a key cannot, because there is exactly one
place the environment is read. The same split, for the same reason, as the address in
:mod:`lab_commons.dev.content`, which is handed its records rather than re-walking its targets.

A GIT INSTALL'S COMMIT RIDES IN THE VERSION STRING, so nothing here reads ``direct_url.json``. pip
derives ``<declared>+<sha>`` as the installed version of a VCS install, which means the manifest
line below already distinguishes two checkouts of one declared version, and a second reader over
the install metadata would be a second description of one fact -- free to disagree with the first,
with nothing to say which won. This is the one property that kept motronics' own 59-line
reimplementation of this module alive; it is written down here because a property nobody records
is one the next reader adds a file to recover.

THE UNREADABLE ROW IS KEPT, NEVER DROPPED. A distribution whose name or version cannot be read --
a broken ``.dist-info``, an import hook that moved, a permission the reader did not have -- hashes
identically to a package that is not installed if it is skipped, so a verdict earned WITHOUT it
would be served to a run that has it. Recording the fact is the conservative direction and costs
one line of the manifest.
"""

from __future__ import annotations

import contextlib
import hashlib
import platform
import sys
from collections.abc import Iterable
from importlib import metadata
from typing import Final

__all__ = ['UNREADABLE', 'env_key', 'env_manifest', 'interpreter_identity']

#: What a distribution contributes when its name or version cannot be read. A word rather than an
#: empty string so the manifest line is legible and cannot collide with a real distribution name.
UNREADABLE: Final = 'UNREADABLE'

_KEY_CHARS: Final = 16


def interpreter_identity() -> str:
    """Which Python this is, as ``<implementation>-<version>-<platform>``.

    Its own function so a test can plant a different interpreter without faking an environment: the
    interpreter is the one row of the manifest that is not a distribution, and a key that omitted
    it would call two runs under different Pythons the same environment.
    """
    return f'{platform.python_implementation().lower()}-{platform.python_version()}-{sys.platform}'


def env_manifest(distributions: Iterable[object] | None = None) -> tuple[str, ...]:
    """The environment as READABLE lines: interpreter first, then every distribution, SORTED.

    ``distributions`` is a bag of UNKNOWN objects on purpose -- ``importlib.metadata`` promises
    nothing about their type, and a test passes its own doubles -- so the two attributes are read
    with ``getattr`` and a double has no contract to implement.

    SORTED, because enumeration order cannot be allowed to vary the key: ``importlib.metadata``
    walks ``sys.path`` and promises nothing about the order it yields in, so the same environment
    would otherwise key differently per process and two runs of one environment would be made to
    look different.

    Passed nothing, it reads THIS interpreter's environment; passed a manifest it is inert, which
    is what lets :func:`env_key` be a pure function of its input.

    ``contextlib.suppress`` covers a distribution object that raises on attribute access at all: a
    reader that crashed on one broken install would take the whole verdict down, and the row it
    cannot describe is exactly the row the manifest must not silently omit.
    """
    if distributions is None:
        distributions = metadata.distributions()
    entries = []
    for dist in distributions:
        name = None
        with contextlib.suppress(Exception):
            name = getattr(dist, 'metadata', {})['Name']
        version = getattr(dist, 'version', None)
        entries.append(f'{name or UNREADABLE}=={version or UNREADABLE}')
    return (interpreter_identity(), *sorted(entries))


def env_key(manifest: Iterable[str], *, length: int = _KEY_CHARS) -> str:
    """A stable short key OF *manifest*. The key is a function of the lines and of nothing else.

    Refuses an EMPTY manifest rather than keying nothing: an environment nobody described is not a
    clean environment, and a dropped manifest that hashed to a constant would make every verdict
    earned without one look identical.

    Raises:
        ValueError: *length* is not positive, or *manifest* yielded no lines.

    """
    if length <= 0:
        msg = f'an environment key of {length} characters names nothing; a floor is required.'
        raise ValueError(msg)
    lines = tuple(manifest)
    if not lines:
        msg = (
            'an empty manifest names no environment. "I described nothing" and "nothing differs" '
            'would be the same key, and a verdict carrying it could be cited against any box.'
        )
        raise ValueError(msg)
    return hashlib.sha256('\n'.join(lines).encode('utf-8')).hexdigest()[:length]
