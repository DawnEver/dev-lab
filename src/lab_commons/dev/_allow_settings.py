"""The SETTINGS-DOCUMENT half of the allow registry: reading a permission row, and merging a section.

SPLIT OUT OF :mod:`lab_commons.dev.allow_adoption` at the seam that module's own first sentence
names -- "two hand-written files that speak about the same thing". One of them is the deny registry,
whose rows DERIVE the block; the other is ``.claude/settings.json``, an arbitrary JSON document this
package is a guest in. Those are different subjects with different failure modes, and the family
already has the shape: :mod:`lab_commons.dev.famconfig` is the write half over
``_famconfig_survey``'s readings, and the import runs one way -- measuring a document does not need
the thing that derives its contents.

PRIVATE, because it is the survey half and the surface a consumer imports is one name. Every
function here is re-exported or wrapped by :mod:`lab_commons.dev.allow_adoption`.

EVERY BODY HERE TAKES A PARSED MAPPING, NEVER A PATH. That is what lets a planted control drive
THESE functions against a dict rather than re-implementing them and agreeing with itself, and it is
also the line between this module and :mod:`lab_commons.dev.famtests.allowguard`: the guard opens
the committed files and drives ``node``; nothing here touches a filesystem.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any, Final

__all__ = ['BASH', 'ROW', 'block_problems', 'live_bash_rows', 'merged_permissions', 'promised_command']

#: A permission row's shape: a tool name and its parenthesised argument. Matched so a row that is
#: not one is refused where it is authored rather than shipped into a file the agent client parses
#: silently -- a line the client ignores, that a reader takes for a permission, is the lie.
ROW: Final = re.compile(r'([A-Za-z]\w*)\((.*)\)', flags=re.DOTALL)

#: The tool whose rows a shell deny engine could ever refuse. Any other tool's rows promise nothing
#: this package can judge, so they are passed through unread rather than dropped.
BASH: Final = 'Bash'


def promised_command(entry: str) -> str | None:
    """The concrete command one ``Bash(...)`` row promises, or ``None`` for another tool's row.

    The same instantiation :func:`lab_commons.dev.famtests.allowguard.probe_command` performs, and
    the sameness is a PROPERTY a consumer pins rather than a coincidence: the two bodies answer the
    same question about the same glob spelling, and a drift between them would let a row this
    package derived be refused by the guard that checks it. Leading and trailing ``*`` are DROPPED
    and an interior one becomes one opaque word, which is the most permissive reading of the row --
    the reading under which a refusal really is a contradiction.
    """
    found = ROW.fullmatch(entry.strip())
    if found is None or found.group(1) != BASH:
        return None
    return ' '.join(re.sub(r'\*+', ' ARG ', found.group(2).strip().strip('*')).split())


def live_bash_rows(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """Every ``Bash(...)`` row already in a settings document's ``permissions.allow``, in file order.

    An absent ``permissions``, an absent ``allow`` and a null one all read as no rows, because the
    caller that cares -- :func:`block_problems` -- is about to report every DERIVED row as missing,
    which is the honest answer for a document that declares nothing. Nothing is raised here: this
    body reads a mapping somebody already parsed, and refusing an unreadable FILE is
    :func:`lab_commons.dev.famtests.allowguard.allow_entries`'s job and stays there.
    """
    rows = (settings.get('permissions') or {}).get('allow') or []
    return tuple(str(row) for row in rows if promised_command(str(row)) is not None)


def merged_permissions(settings: Mapping[str, Any], entries: Sequence[str]) -> dict[str, Any]:
    """*settings* with its ``permissions.allow`` Bash rows replaced by *entries*. A SECTION MERGE.

    Every other top-level key, and every other key inside ``permissions``, is carried through
    untouched -- ``hooks`` belongs to :func:`lab_commons.dev.agent_guard.wire_settings` and
    ``deny``/``ask`` belong to whoever wrote them. That is the whole reason the allow half is not a
    :mod:`lab_commons.dev.famconfig` artefact: a WHOLE-FILE renderer keyed by filename would have to
    own the blocks it is not about, or clobber them, and it would open a JSON file with a comment.

    ``Bash`` rows are REPLACED rather than merged, because they are exactly the population this
    package owns and a merge would let a hand-written one survive forever. Rows of any other tool
    are preserved AHEAD of the rendered block: nothing here can judge what ``Read(**)`` promises,
    and silently dropping it would be this package deciding a question it cannot read.
    """
    document = dict(settings)
    permissions = dict(document.get('permissions') or {})
    ours = set(live_bash_rows(settings))
    foreign = [str(row) for row in (permissions.get('allow') or []) if str(row) not in ours]
    permissions['allow'] = [*foreign, *entries]
    document['permissions'] = permissions
    return document


def block_problems(
    settings: Mapping[str, Any],
    rendered: Sequence[str],
    provenance: Mapping[str, str],
) -> tuple[str, ...]:
    """BOTH SIDES of the ratchet between the *rendered* block and the one on disk, as named sets.

    A rendered row MISSING from the document is the 2026-09-18 incident itself -- the remedy exists,
    the deny engine permits it, and the permission layer refuses it -- and a scan that only looked
    for unexpected rows would have reported that tree clean. A row on disk that is in neither
    population is the other side: the hand edit, arriving with no argument for itself.

    *provenance* is carried into the message rather than looked up, because "derived from
    RAW-PROCESS-KILL" and "declared: the docs preview server" are two different repairs and a
    missing-row report that cannot say which one it is sends the reader to the wrong file.
    """
    live = set(live_bash_rows(settings))
    out = [f'missing: {entry}  ({provenance.get(entry, "no provenance")})' for entry in rendered if entry not in live]
    out += [
        f'undeclared: {entry}  -- neither a remedy this repo supplies nor a declared road'
        for entry in sorted(live - set(rendered))
    ]
    return tuple(out)
