"""A REVIEW ROUND'S SUMMARY: what the PR does, as the engine said it, and what changed and why, as git says it.

Split from :mod:`dev_lab.dev.forgereview_rounds` (2026-11-03, the module-size band): the two readings that OPEN a
round's comment. :func:`what_it_does` renders the engine's summary with its cites linked; :func:`context_summary`
is round 1's shared context -- the files and layers changed, and the WHY cited from each of :data:`SUMMARY_CITES`.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any, Final

from dev_lab.dev.forgereview_scope import git

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from dev_lab.dev._forgebackends import Backend

__all__ = ['SUMMARY_CITES', 'context_summary', 'repo_url', 'what_it_does']

#: What a review's context summary cites as the change's WHY, in order: its commits, the memory entries it lands,
#: the merge audit of its merges, and the PR body. Exported by :mod:`dev_lab.dev.reviewpolicy` for every trigger.
SUMMARY_CITES: Final = ('commits', 'memory', 'merge_audit', 'pr_body')

_ANY_EXIT: Final = range(256)  # a read whose failure reads as empty: the summary degrades, never stops
_SUBJECTS: Final = 20  # commit subjects (memory paths, merges) the summary lists
_SHA: Final = re.compile(r'^[0-9a-f]{7,40}$')
_MEMORY: Final = '.claude/memory/'


def _bullets(rows: list[str]) -> str:
    more = f'\n- ... and {len(rows) - _SUBJECTS} more' if len(rows) > _SUBJECTS else ''
    return '\n'.join(f'- {one}' for one in rows[:_SUBJECTS]) + more


def context_summary(root: Path, reviewed: str, pr_body: str = '') -> str:
    """What changed over *reviewed*, in which layers, and WHY -- cited from each of :data:`SUMMARY_CITES` in order."""
    _, numstat = git(root, 'diff', '--no-renames', '--numstat', reviewed, ok=_ANY_EXIT)
    layers: dict[str, list[int]] = {}
    for row in numstat.splitlines():
        added, removed, path = [*row.split('\t'), '', '', ''][:3]
        layer = '/'.join(PurePosixPath(path).parts[:-1][:3]) or '.'
        tally = layers.setdefault(layer, [0, 0, 0])
        tally[0] += 1
        tally[1] += int(added) if added.isdigit() else 0
        tally[2] += int(removed) if removed.isdigit() else 0
    files = sum(t[0] for t in layers.values())
    plus, minus = sum(t[1] for t in layers.values()), sum(t[2] for t in layers.values())
    where = ', '.join(f'`{name}` ({t[0]})' for name, t in sorted(layers.items(), key=lambda kv: -kv[1][0]))
    _, log = git(root, 'log', '--no-merges', '--format=%s', reviewed, ok=_ANY_EXIT)
    _, merges = git(root, 'log', '--merges', '--format=%s', reviewed, ok=_ANY_EXIT)
    _, landed = git(
        root, 'diff', '--no-renames', '--diff-filter=A', '--name-only', reviewed, '--', _MEMORY, ok=_ANY_EXIT
    )
    lead = pr_body.strip().split('\n\n', 1)[0]
    cited = {
        'commits': '**Why** (the commits):\n' + (_bullets([one for one in log.splitlines() if one.strip()])
                                                  or '- (no commits)'),
        'memory': _bullets([f'`{one}`' for one in landed.splitlines() if one.strip()]),
        'merge_audit': _bullets([one for one in merges.splitlines() if one.strip()]),
        'pr_body': '\n'.join(f'> {line}' for line in lead.splitlines()),
    }  # fmt: skip
    titles = {'memory': '**Memory** (the entries landed):\n', 'merge_audit': '**Merges** (the merges):\n',
              'pr_body': '**PR body**:\n'}  # fmt: skip
    why = [titles.get(cite, '') + cited[cite] for cite in SUMMARY_CITES if cited[cite]]
    head = f'**What changed**: {files} file(s), +{plus}/-{minus}, in {len(layers)} layer(s): {where or "none"}.'
    return '\n\n'.join([head, *why])


def repo_url(pull_url: str) -> str:
    """The web root of the repository a PR or ledger-issue page is in (``/pulls/N``, ``/pull/N``, ``/issues/N``)."""
    return pull_url.rsplit('/pulls/', 1)[0].rsplit('/pull/', 1)[0].rsplit('/issues/', 1)[0]


def _cite(cite: str, repo: str, head: str, backend: Backend) -> str:
    """One cite as a link: a commit sha to the commit, anything else as a path in the tree at *head*."""
    if _SHA.match(cite):
        return f'[`{cite[:12]}`]({backend.commit_url(repo, cite)})'
    return f'[`{cite}`]({backend.file_url(repo, head, cite)})'


def what_it_does(summary: Mapping[str, Any] | None, repo: str, head: str, backend: Backend) -> str:
    """The engine's *summary* as the comment's opening section ("What this PR does"); empty when none.

    Its cites link in *backend*'s URL forms under the web root *repo*.
    """
    if summary is None:
        return ''
    if summary.get('error'):
        return f'### What this PR does\nThe engine could not summarize this head: {summary["error"]}'
    rows = []
    for change in summary.get('changes', ()):
        cites = ', '.join(_cite(str(one), repo, head, backend) for one in change.get('cites', ()))
        rows.append(f'- {change["claim"]}' + (f' ({cites})' if cites else ''))
    parts = ['### What this PR does\n' + ('\n'.join(rows) or '- (no claims)')]
    for key, title in (
        ('tests_altered', 'Tests altered'),
        ('resolutions', 'Resolutions'),
        ('open_items', 'Open items'),
    ):
        if items := summary.get(key):
            parts.append(f'**{title}**:\n' + '\n'.join(f'- {one}' for one in items))
    return '\n\n'.join(parts)
