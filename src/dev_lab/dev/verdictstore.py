"""A VERDICT BY CONTENT KEY -- the run-records store read as (tree, env key, part) -> a PASS to cite (D50-1).

A verdict is a fact about a :class:`ContentKey`: the committed tree (``HEAD^{tree}``), the environment key ``verify``
prints (:func:`lab_commons.envkey.env_key`) and the part. :func:`lookup` finds the newest stored FULL record of the
key whose part is a PASS -- a record of another sha with the SAME tree is a hit; another tree, another env key, a
selection, a FAIL (a re-run may pass: a FAIL is never sticky) or a record of a revoked box
(:mod:`dev_lab.dev.workstationrevoke`) never is. :func:`cite` posts it on a sha through the status door, the record
as its ``target_url``. (REACH-CARRY, :mod:`dev_lab.dev.forgecarry`, carries ACROSS trees; this is the exact tree.)
"""

from __future__ import annotations

import gzip
import json
import subprocess
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import lab_commons.launch as _door
from lab_commons.outcomes import Conclusion

from dev_lab.dev.forgerecords import listing
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.platformparts import PartRefusal, part_context, part_of
from dev_lab.dev.workstationrevoke import box_of

if TYPE_CHECKING:
    from pathlib import Path

    from dev_lab.dev.forgerecords import Attachment
    from dev_lab.dev.forgework import Client

__all__ = ['WORKSTATION_KEY', 'ContentKey', 'Found', 'cite', 'lookup', 'trees_of']

#: The record key naming the workstation that produced it; absent on a forge producer's record.
WORKSTATION_KEY: Final = 'workstation'

_GIT_TIMEOUT_S: Final = 60

#: How many hex digits a full commit sha has.
_SHA_HEX: Final = 40


@dataclass(frozen=True)
class ContentKey:
    """What a part's verdict is a fact about: the committed tree, the env key and the part."""

    tree: str
    env: str
    part: str


@dataclass(frozen=True)
class Found:
    """A stored PASS record proving a key: its attachment and its record."""

    attachment: Attachment
    record: Mapping[str, Any]

    @property
    def workstation(self) -> str:
        """The box the record says produced it, ``''`` when it names none."""
        return str(self.record.get(WORKSTATION_KEY, ''))

    @property
    def result(self) -> Conclusion:
        """The conclusion it proves."""
        return part_of(self.record).result


def trees_of(root: Path, shas: Collection[str]) -> dict[str, str]:
    """``{sha: its tree}`` for each of *shas* this checkout holds, read on stdin (no argv limit).

    Raises:
        OSError: git could not answer -- never read as "no trees".

    """
    ordered = sorted(shas)
    if not ordered:
        return {}
    try:
        done = _door.run(
            ['git', 'cat-file', '--batch-check=%(objectname) %(objecttype)'], cwd=root, capture_output=True,
            text=True, encoding='utf-8', check=False, timeout=_GIT_TIMEOUT_S,
            input=''.join(f'{sha}^{{tree}}\n' for sha in ordered),
        )  # fmt: skip
    except subprocess.TimeoutExpired as late:
        raise OSError(str(late)) from late
    lines = done.stdout.splitlines()
    if done.returncode != 0 or len(lines) != len(ordered):
        msg = f'git cat-file could not read the trees of {len(ordered)} sha(s): {done.stderr.strip()[:200]}'
        raise OSError(msg)
    return {sha: line.split()[0] for sha, line in zip(ordered, lines, strict=True) if line.endswith(' tree')}


def _sha_part(name: str) -> tuple[str, str] | None:
    """``(sha, part)`` of a run record's name ``run-<sha>-<part>-<req>[-<hash>].json.gz``; ``None`` otherwise."""
    if not name.startswith('run-') or not name.endswith('.json.gz'):
        return None
    sha, _, rest = name[4:].partition('-')
    part, _, _ = rest.partition('-')
    return (sha, part) if len(sha) == _SHA_HEX and part else None


def _passes(record: Mapping[str, Any], key: ContentKey, revoked: Collection[str]) -> bool:
    if record.get('env') != key.env or record.get('scope') != 'full' or record.get('platform') != key.part:
        return False
    if (box := record.get(WORKSTATION_KEY)) and box_of(str(box)) in revoked:
        return False
    try:
        return part_of(record).result is Conclusion.PASS
    except PartRefusal:
        return False


def lookup(
    root: Path,
    client: Client,
    key: ContentKey,
    *,
    revoked: Collection[str],
    download: Callable[[str], bytes] | None = None,
) -> Found | None:
    """The newest stored full PASS record of *key*, of no *revoked* box (module docstring); ``None`` on no hit."""
    named = [(item, found) for item in listing(client) if (found := _sha_part(item.name)) and found[1] == key.part]
    trees = trees_of(root, {sha for _, (sha, _) in named})
    fetch = download or client.download
    for item, (sha, _) in sorted(named, key=lambda one: one[0].id, reverse=True):  # newest: the forge's id
        if trees.get(sha) != key.tree:
            continue
        record = json.loads(gzip.decompress(fetch(item.url)).decode('utf-8'))
        if _passes(record, key, revoked):
            return Found(item, record)
    return None


def cite(client: Client, sha: str, found: Found) -> str:
    """Post *found*'s part on *sha* through the status door, its record as the target; the line."""
    part = part_of(found.record)
    status_post(
        client, sha, context=part_context(part.platform), state=part.state, description=part.description(),
        target_url=found.attachment.url,
    )  # fmt: skip
    by = f'workstation {found.workstation}' if found.workstation else 'a forge producer'
    return f'[verdictstore] {part.platform} part {part.result.name} CITED from {found.attachment.name} ({by})'
