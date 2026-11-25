"""Remote TAG deletion, beside :mod:`dev_lab.dev.branchdelete`: only a tag whose commit declared history contains.

Split out of :mod:`dev_lab.dev.branchdelete` (2026-11-25, MODULE-SIZE-ALARM) along its own seam: a tag is judged
by ancestry alone and never by content, so it shares none of the branch judgment, only the door that runs it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from dev_lab.dev.checkout import git_out
from dev_lab.dev.deletejudge import ORIGIN
from dev_lab.dev.forge import _GIT
from dev_lab.dev.lanepolicy import load_policy
from dev_lab.dev.netverb import run_network_verb

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

__all__ = ['CONTAINED_TAG_DOOR', 'TAG_EVENT', 'delete_contained_tags']

#: The door an agent deletes a remote TAG through: only one whose commit integration or the trunk contains.
CONTAINED_TAG_DOOR: Final = 'python -m dev_lab.dev.branchprune tag <tag>'
#: The ``event`` of the record each tag deletion writes BEFORE its push (name, ref sha, commit).
TAG_EVENT: Final = 'lab_commons.forge.tag-delete'


def _origin_tag(root: Path, tag: str) -> tuple[str, str]:
    """``(ref sha, commit sha)`` of origin's *tag* (an annotated tag peeled); ``('', '')`` when origin has none."""
    listed = git_out(root, 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}', f'refs/tags/{tag}^{{}}') or ''
    shas = {name: sha for sha, _, name in (line.partition('	') for line in listed.splitlines())}
    ref = shas.get(f'refs/tags/{tag}', '')
    return ref, shas.get(f'refs/tags/{tag}^{{}}', ref)


def _push_tag_delete(root: Path, tag: str, sha: str) -> str:
    """Delete origin's *tag* if still at *sha* (a lease), through the network door; ``''``, or why not."""
    report = run_network_verb(
        [_GIT, 'push', f'--force-with-lease=refs/tags/{tag}:{sha}', 'origin', '--delete', f'refs/tags/{tag}'],
        cwd=root,
        timeout=300,
    )
    return '' if report.ok else report.remedy


def delete_contained_tags(
    root: Path,
    tags: Sequence[str],
    *,
    fetch: Callable[[Path], None],
    say: Callable[[str], None],
    push: Callable[[Path, str, str], str] = _push_tag_delete,
) -> int:
    """Delete each origin tag whose commit origin's trunk or integration contains; 0 when every one went, else 1.

    A tag holds nothing of its own only when its commit is in declared history, so that is the whole judgment
    (by ancestry; a tag is never judged by content). Each deletion is RECORDED -- name, ref sha, commit -- before
    its push, so the tag can be recreated from the record; a tag naming uncontained work is kept and named.
    """
    fetch(root)
    policy = load_policy(root)
    failed = 0
    for tag in tags:
        ref, commit = _origin_tag(root, tag)
        if not ref:
            say(f'{tag}: origin holds no such tag')
            failed += 1
            continue
        holder = next(
            (
                name
                for name in (policy.trunk, policy.integration)
                if git_out(root, 'merge-base', '--is-ancestor', commit, f'{ORIGIN}{name}') is not None
            ),
            '',
        )
        if not holder:
            say(f'{tag}: kept -- {commit[:12]} is in neither origin/{policy.trunk} nor origin/{policy.integration}')
            failed += 1
            continue
        say(json.dumps({'event': TAG_EVENT, 'ref': tag, 'sha': ref, 'commit': commit, 'container': holder}))
        if why := push(root, tag, ref):
            say(f'{tag}: the delete failed: {why}')
            failed += 1
            continue
        say(f'{tag}: deleted at {commit[:12]} -- held by {holder}')
    return 1 if failed else 0
