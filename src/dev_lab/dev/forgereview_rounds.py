"""REVIEW ROUNDS: a PR's findings carried head to head, closed by a fix or a disposition, blocking while open.

User ruling 2026-10-26. A finding is TAGGED (``severity``, ``security``, ``rule``) under an id stable across rounds
(ai-lab's hash of rule, file and anchor line). Each reviewed head is one ROUND, recorded as a :class:`Ledger` in the
head's findings comment (a hidden ``review-ledger`` line); the next round starts from the newest one.

* ROUND 1 reviews the whole branch change, and its comment opens with a :func:`context_summary` -- what changed,
  why (the commit subjects), which layers -- the team's shared context.
* ROUND k > 1 reviews only what the branch added since its last reviewed head
  (:func:`dev_lab.dev.forgereview_scope.own_base`) and RE-CHECKS every open finding: one whose anchor line is
  gone from its file at the new head is CLOSED as fixed. NO MOVING GOALPOSTS: a new finding below ``HIGH`` whose
  anchor is not a line the round added is dropped -- a later round may not raise a non-HIGH finding on a line
  the earlier rounds already read.
* PAST ``max_rounds`` no command runs: the open BLOCKING findings are re-checked alone, and the open non-blocking
  ones leave the ledger for ONE follow-up issue.

A finding BLOCKS while open when it is ``HIGH`` or a security finding (:attr:`Finding.blocking`). The head's
:data:`~dev_lab.dev.platformparts.REVIEW_CONTEXT` is ``failure`` while any blocking finding is open and not
DISPOSED, else ``success``; the auto-merge waits on that failure (:func:`dev_lab.dev.forgemerge.review_blocks`).
A disposition is the integrator's, posted through ``forge review dispose`` (:mod:`dev_lab.dev.forgereview_dispose`)
as a keyed comment (``Marker.DISPOSITION``) carrying its reason.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

import lab_commons.launch as _door

from dev_lab.dev.forgepulls import Marker, comment_list, comment_upsert, marker
from dev_lab.dev.forgereview_findings import SEVERITIES, Finding, Findings
from dev_lab.dev.forgestatus import status_post
from dev_lab.dev.forgework import ACTIONS_BOT, GITHUB
from dev_lab.dev.platformparts import REVIEW_CONTEXT

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from dev_lab.dev.forgework import Client, PullRequest

__all__ = [
    'DISPOSE_DOOR', 'FAMILY_MAX_ROUNDS', 'LEDGER_VERSION', 'Ledger', 'advance', 'blocking', 'capped', 'context_summary',
    'disposed', 'disposition_text', 'ledger_of', 'post_round', 'render', 'trusted_bodies', 'verdict',
]  # fmt: skip

#: The family's cap on full review rounds per PR; a repo declares ``max_rounds`` only to differ.
FAMILY_MAX_ROUNDS: Final = 3

#: The ledger's format version; a ledger of another version is refused, never guessed at.
LEDGER_VERSION: Final = 1

#: The door the integrator disposes of a finding through; ``{pr}`` and ``{id}`` are filled.
DISPOSE_DOOR: Final = 'python -m dev_lab.dev.forge review dispose {pr} {id} --why "<reason>"'

_LEDGER: Final = re.compile(r'<!-- review-ledger (?P<json>\{.*?\}) -->', re.DOTALL)
_DISPOSED: Final = re.compile(
    re.escape(marker(Marker.DISPOSITION, 'KEY')).replace('KEY', r'(?P<key>\S+)')
    + r'\n\*\*Disposed\*\* `(?P<id>[^`]+)` by (?P<who>\S+): (?P<why>.+)$',
    re.MULTILINE,
)
_GIT_TIMEOUT_S: Final = 120
_SUBJECTS: Final = 20  # commit subjects the summary lists
_DESCRIPTION: Final = 240  # a commit-status description is short


@dataclass(frozen=True)
class Ledger:
    """One round's record: the head it reviewed, its number, what stays open and what closed in it."""

    head: str
    round: int
    open: tuple[Finding, ...] = ()
    closed: tuple[tuple[str, str], ...] = ()  # (id, how) closed THIS round
    deferred: tuple[Finding, ...] = ()  # non-blocking, moved to the follow-up issue THIS round

    def line(self) -> str:
        """The hidden comment line that records this ledger (``>`` escaped, so the JSON cannot close the comment)."""
        doc = {
            'version': LEDGER_VERSION, 'head': self.head, 'round': self.round,
            'open': [asdict(one) for one in self.open],
        }  # fmt: skip
        text = json.dumps(doc, ensure_ascii=False).replace('>', '\\u003e')
        return f'<!-- review-ledger {text} -->'


def trusted_bodies(client: Client, number: int) -> list[str]:
    """PR *number*'s comment bodies (oldest first) the forge records as written by THIS client's login.

    A ledger or a disposition is state the forge and the integrator write; a comment anyone else writes that
    merely LOOKS like one (an author pasting a disposition) is never read as one. On GitHub the review's own
    rounds are written by the workflow job token, so :data:`~dev_lab.dev.forgework.ACTIONS_BOT` is trusted too.
    """
    trusted = {client.whoami(), *((ACTIONS_BOT,) if client.backend is GITHUB else ())}
    return [comment.body for comment in comment_list(client, number) if comment.author in trusted]


def _finding(row: Mapping) -> Finding:
    return Finding(**{**row, 'reviewers': tuple(row.get('reviewers', ()))})


def ledger_of(bodies: Iterable[str]) -> Ledger | None:
    """The newest ledger the PR comment *bodies* (oldest first) carry, else ``None``; another version is refused."""
    found = None
    for body in bodies:
        if (match := _LEDGER.search(body)) is not None:
            found = json.loads(match['json'])
    if found is None:
        return None
    if found.get('version') != LEDGER_VERSION:
        msg = f'a review ledger of version {found.get("version")!r}; this reader knows {LEDGER_VERSION}'
        raise ValueError(msg)
    return Ledger(found['head'], int(found['round']), tuple(_finding(row) for row in found['open']))


def disposition_text(finding_id: str, who: str, why: str) -> str:
    """The body of a disposition comment (after its marker): who disposed of *finding_id*, and why."""
    return f'**Disposed** `{finding_id}` by {who}: {" ".join(why.split())}'


def disposed(bodies: Iterable[str]) -> dict[str, str]:
    """``{finding id: why}`` of every disposition the PR comment *bodies* carry."""
    return {
        match['id']: match['why']
        for body in bodies
        if (match := _DISPOSED.search(body)) is not None and match['key'] == match['id']
    }


def blocking(ledger: Ledger, gone: Mapping[str, str]) -> tuple[Finding, ...]:
    """The open findings of *ledger* that block the merge: ``HIGH`` or security, and not disposed (*gone*)."""
    return tuple(one for one in ledger.open if one.blocking and one.id not in gone)


def verdict(ledger: Ledger, gone: Mapping[str, str], number: int) -> tuple[str, str]:
    """The ``(state, description)`` of :data:`~dev_lab.dev.platformparts.REVIEW_CONTEXT` for *ledger*."""
    held = blocking(ledger, gone)
    if held:
        ids = ', '.join(one.id for one in held)
        door = DISPOSE_DOOR.format(pr=number, id='<id>')
        return 'failure', f'review round {ledger.round}: {len(held)} blocking finding(s) open ({ids}); fix, or {door}'
    rest = sum(one.id not in gone for one in ledger.open)
    return 'success', f'review round {ledger.round}: no blocking finding open ({rest} open, non-blocking)'


def _git(root: Path, *args: str) -> tuple[int, str]:
    done = _door.run(
        ['git', *args], cwd=root, capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=_GIT_TIMEOUT_S, check=False,
    )  # fmt: skip
    return done.returncode, done.stdout


def _norm(line: str) -> str:
    return ' '.join(line.split())


def _anchored(root: Path, head: str, finding: Finding) -> bool:
    """Whether *finding*'s anchor line is still in its file at *head* (a deleted file has none)."""
    code, text = _git(root, 'show', f'{head}:{finding.file}')
    return code == 0 and _norm(finding.anchor) in {_norm(line) for line in text.splitlines()}


def _added(root: Path, reviewed: str) -> dict[str, set[str]]:
    """``{path: the lines the range *reviewed* added}``, whitespace-normalized."""
    code, text = _git(root, 'diff', '--no-renames', '--unified=0', reviewed)
    if code != 0:
        msg = f'git diff {reviewed} failed in {root}'
        raise OSError(msg)
    out: dict[str, set[str]] = {}
    path = ''
    for line in text.splitlines():
        if line.startswith('+++ '):
            path = line[6:] if line.startswith('+++ b/') else ''
        elif line.startswith('+') and path:
            out.setdefault(path, set()).add(_norm(line[1:]))
    return out


def advance(root: Path, head: str, reviewed: str, prior: Ledger | None, found: Findings | None) -> Ledger:
    """The ledger of *head*'s round: *prior*'s open findings re-checked, *found*'s merged in by id.

    *found* is ``None`` past the cap (no command ran): only blocking findings stay, the rest are deferred.
    """
    number = 1 if prior is None else prior.round + 1
    kept: dict[str, Finding] = {}
    closed: list[tuple[str, str]] = []
    for one in () if prior is None else prior.open:
        if _anchored(root, head, one):
            kept[one.id] = one
        else:
            closed.append((one.id, f'fixed: its anchor line is gone from {one.file}'))
    if found is None:
        deferred = tuple(one for one in kept.values() if not one.blocking)
        stays = tuple(one for one in kept.values() if one.blocking)
        return Ledger(head, number, stays, tuple(closed), deferred)
    added = _added(root, reviewed) if number > 1 else {}
    for one in found.findings:
        if one.id in kept or number == 1 or one.severity == SEVERITIES[0]:
            kept[one.id] = one
        elif _norm(one.anchor) in added.get(one.file, set()):
            kept[one.id] = one  # new, below HIGH, but on a line this round added: not a moved goalpost
    return Ledger(head, number, tuple(kept.values()), tuple(closed))


def context_summary(root: Path, reviewed: str) -> str:
    """What changed over *reviewed*, why (its commit subjects) and in which layers: round 1's shared context."""
    _, numstat = _git(root, 'diff', '--no-renames', '--numstat', reviewed)
    layers: dict[str, list[int]] = {}
    for row in numstat.splitlines():
        added, removed, path = [*row.split('\t'), '', '', ''][:3]
        layer = '/'.join(PurePosixPath(path).parts[:-1][:3]) or '.'
        tally = layers.setdefault(layer, [0, 0, 0])
        tally[0] += 1
        tally[1] += int(added) if added.isdigit() else 0
        tally[2] += int(removed) if removed.isdigit() else 0
    _, log = _git(root, 'log', '--no-merges', '--format=%s', reviewed)
    subjects = [line for line in log.splitlines() if line.strip()]
    files = sum(t[0] for t in layers.values())
    plus, minus = sum(t[1] for t in layers.values()), sum(t[2] for t in layers.values())
    where = ', '.join(f'`{name}` ({t[0]})' for name, t in sorted(layers.items(), key=lambda kv: -kv[1][0]))
    why = '\n'.join(f'- {one}' for one in subjects[:_SUBJECTS])
    more = f'\n- ... and {len(subjects) - _SUBJECTS} more' if len(subjects) > _SUBJECTS else ''
    return (
        f'**What changed**: {files} file(s), +{plus}/-{minus}, in {len(layers)} layer(s): {where or "none"}.\n\n'
        f'**Why** (the commits):\n{why or "- (no commits)"}{more}'
    )


def _row(one: Finding, number: int) -> str:
    tags = f'**{one.severity}**{" **security**" if one.security else ""}'
    by = f'; by {", ".join(one.reviewers)}' if one.reviewers else ''
    lines = [f'- {tags} `{one.file}` -- {one.summary} (`{one.id}`, rule `{one.rule}`{by})']
    lines.append(f'  - anchor: `{one.anchor.strip()}`')
    if one.suggestion:
        lines.append(f'  - suggestion: {one.suggestion}')
    if one.blocking:
        lines.append(f'  - dispose: `{DISPOSE_DOOR.format(pr=number, id=one.id)}`')
    return '\n'.join(lines)


def render(
    ledger: Ledger, gone: Mapping[str, str], *, number: int, reviewed: str, max_rounds: int,
    found: Findings | None, summary: str = '',
) -> str:  # fmt: skip
    """The round's one PR comment: verdict, (round 1) the context summary, the findings by standing, the ledger."""
    state, said = verdict(ledger, gone, number)
    capped = ' -- past the cap: blocking findings re-checked only, no reviewer ran' if found is None else ''
    head = f'**Review round {ledger.round}/{max_rounds}** of `{ledger.head[:12]}` over `{reviewed}`{capped}'
    parts = [f'{head}\n\n`tests/review` {state}: {said}']
    if summary:
        parts.append(summary)
    if found is not None:
        who = ', '.join(f'`{one.name}` ({one.provider or "-"}): {one.status}' for one in found.reviewers) or 'none'
        parts.append(f'Reviewers: {who}')
    order = sorted(ledger.open, key=lambda one: (not one.blocking, SEVERITIES.index(one.severity)))
    held = [_row(one, number) for one in order if one.blocking and one.id not in gone]
    rest = [_row(one, number) for one in order if not one.blocking and one.id not in gone]
    sections = (
        ('Blocking (open)', held),
        ('Open, not blocking', rest),
        ('Closed this round', [f'- `{fid}` {how}' for fid, how in ledger.closed]),
        ('Disposed', [f'- `{fid}`: {why}' for fid, why in gone.items() if any(one.id == fid for one in ledger.open)]),
        ('Moved to the follow-up issue', [f'- `{one.id}` {one.summary}' for one in ledger.deferred]),
    )
    parts += [f'### {title}\n' + '\n'.join(rows) for title, rows in sections if rows]
    if not ledger.open and not ledger.closed:
        parts.append('No findings.')
    parts.append(ledger.line())
    return '\n\n'.join(parts)


def _follow_up(client: Client, pull: PullRequest, ledger: Ledger) -> None:
    """ONE follow-up issue for the non-blocking findings *ledger* moved out at the cap (none: nothing written)."""
    if not ledger.deferred:
        return
    rows = '\n'.join(
        f'- `{one.id}` {one.severity} `{one.file}` -- {one.summary} (rule `{one.rule}`)' for one in ledger.deferred
    )
    body = (
        f'Non-blocking review findings of #{pull.number} ({pull.head}) still open past the round cap: they no '
        f'longer hold the PR, and are tracked here.\n\n{rows}'
    )
    client.issue_create(f'review follow-up: #{pull.number} {pull.head}', body)


def post_round(
    root: Path, client: Client, pull: PullRequest, reviewed: str, *, found: Findings | None, max_rounds: int,
    by: str = 'review',
) -> str:  # fmt: skip
    """Post *pull*'s head review round: its comment, :data:`REVIEW_CONTEXT`, any follow-up issue; the line said.

    *found* is ``None`` past the cap (no command ran). *by* names who reviewed, for the status.
    """
    head = pull.head_sha
    bodies = trusted_bodies(client, pull.number)
    prior = ledger_of(bodies)
    prior = None if prior is not None and prior.head == head else prior  # a head re-posted is not a new round
    ledger = advance(root, head, reviewed, prior, found)
    gone = disposed(bodies)
    summary = context_summary(root, reviewed) if ledger.round == 1 else ''
    text = render(ledger, gone, number=pull.number, reviewed=reviewed, max_rounds=max_rounds,
                        found=found, summary=summary)  # fmt: skip
    _, comment = comment_upsert(client, pull.number, kind=Marker.REVIEW, key=head, text=text)
    _follow_up(client, pull, ledger)
    state, said = verdict(ledger, gone, pull.number)
    status_post(client, head, context=REVIEW_CONTEXT, state=state, target_url=comment.url if comment else '',
                description=f'{by}: {said}'[:_DESCRIPTION])  # fmt: skip
    return f'#{pull.number} {head[:12]}: {by} round {ledger.round}, {state}: {said}'


def capped(client: Client, pull: PullRequest, max_rounds: int) -> bool:
    """Whether *pull* has had its ``max_rounds`` full rounds: its next head is re-checked only."""
    prior = ledger_of(trusted_bodies(client, pull.number))
    return prior is not None and prior.head != pull.head_sha and prior.round >= max_rounds
