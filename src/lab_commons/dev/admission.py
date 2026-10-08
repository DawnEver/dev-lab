"""PUSH ADMISSION -- the family's ONE answer to "may this push go", read off the verdict LEDGER.

THE RULE (user rulings 2026-10-04, 2026-10-07 and 2026-10-08, ONE-RUN-AFTER-INTEGRATION):

==================  =============================================  =======================
destination         admitted                                       refused
==================  =============================================  =======================
a lane              always -- a lane carries no verdict of its own  nothing
an integration ref  a PASS or FAIL recorded for HEAD, in this env   no such entry; dirty
the trunk           a PASS of a trunk tier, for HEAD, in this env   everything else
==================  =============================================  =======================

ONE RUN AFTER INTEGRATION. Every lane verifying itself was the second source of duplicate runs
measured 2026-10-08: N lanes paid N suites, and the main session then paid one more on the merged
tree, which is the only tree that is ever published to integration. So a lane is never judged on its
own; the main session merges every ready lane into one integration tree and runs the gate ONCE, and
the verdict it records is the one the integration push cites. A lane push therefore needs no
verdict -- what it still needs is the merge audit below.

THE LEDGER IS THE ONE SOURCE (:mod:`lab_commons.dev.verdictledger`). The runner records a run-level
entry after PROMOTION, naming HEAD only when the tree was clean and unmoved across the run; this
module reads those entries and never parses a log. An INCONCLUSIVE never reaches the ledger, so "a
run that never started" needs no reading of its own here. A cited FAIL writes the gap record from
the ledger's own per-test FAIL rows for the same tree and env.

EVERY DESTINATION AUDITS THE MERGES IT PUBLISHES, unconditionally: each merge commit not yet on any
remote must name every test its resolution lost or rewrote (:mod:`lab_commons.dev.mergeaudit`).

THE STAMP GRAMMAR'S READER STAYS HERE. Runners still stamp their logs (``[verdict tree= env= tier=
selector=] RESULT`` and :mod:`lab_commons.dev.verify`'s flat line) as the evidence a ledger entry
points at, and :func:`parse_verdict_line` is the one reader of both. It no longer decides a push.

WHY HERE AND NOT IN EACH CONSUMER. Three repos each carried a copy of this table and the copies
disagreed. :mod:`lab_commons.dev.famtests.localadmission` refuses a consumer that keeps one.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.envkey import env_key, env_manifest
from lab_commons.dev.forge import _GIT
from lab_commons.dev.integrator import Policy, load_policy
from lab_commons.dev.logref import MARKER
from lab_commons.dev.mergeaudit import TRAILER, MergeAuditError, refusals
from lab_commons.dev.treedirt import status_paths
from lab_commons.dev.verdictledger import Entry, entries, ledger_path
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

__all__ = [
    'INTEGRATION',
    'LANE',
    'RESULTS',
    'TRUNK',
    'VERDICT_STAMP',
    'Admission',
    'CitedVerdict',
    'admit',
    'destination_of',
    'main',
    'merge_refusals',
    'parse_verdict_line',
    'record_gap',
    'unpublished_merges',
]

#: The tiered stamp a consumer's gate runner writes: ``[verdict tree= env= tier= selector=] RESULT``.
VERDICT_STAMP: Final = '[verdict '

_TIERED: Final = re.compile(
    re.escape(VERDICT_STAMP)
    + r'tree=(?P<tree>\S+) env=(?P<env>\S+) tier=(?P<tier>\S+) selector=\S+\]\s+(?P<result>[A-Z]+)'
)
#: The untiered stamp :mod:`lab_commons.dev.verify` writes (:func:`lab_commons.dev.logref.stamp_line`).
_FLAT: Final = re.compile(
    '^' + re.escape(MARKER) + r'result=(?P<result>\w+) tree=(?P<tree>\S+) env=(?P<env>\S+) ', re.MULTILINE
)

LANE: Final = 'lane'
INTEGRATION: Final = 'integration'
TRUNK: Final = 'trunk'
#: What each JUDGED destination may cite -- the table above, as the one place it is spelled. A lane
#: is absent on purpose: it cites nothing.
RESULTS: Final = {
    INTEGRATION: frozenset({'PASS', 'FAIL'}),
    TRUNK: frozenset({'PASS'}),
}

#: Preference when several entries are citable: the strongest statement about the tree wins.
_RANK: Final = {'PASS': 0, 'FAIL': 1}

_RUN_PREFIX: Final = 'run:'
_GIT_TIMEOUT_S: Final = 120


@dataclass(frozen=True)
class CitedVerdict:
    """One parsed verdict line; ``tier`` is ``None`` for the untiered :mod:`verify` stamp."""

    tree: str
    env: str
    tier: str | None
    result: str
    line: str


@dataclass(frozen=True)
class Admission:
    """The decision, the ledger entry it rests on (``None`` for a lane), and the text the hook prints."""

    allowed: bool
    cited: Entry | None
    message: str


def parse_verdict_line(text: str) -> CitedVerdict | None:
    """The LAST verdict line in *text*, in either grammar -- a verdict is written when a run ENDS."""
    found = [*_TIERED.finditer(text), *_FLAT.finditer(text)]
    if not found:
        return None
    last = max(found, key=lambda m: m.start())
    start = text.rfind('\n', 0, last.start()) + 1
    end = text.find('\n', last.start())
    line = text[start : len(text) if end < 0 else end].strip()
    tier = last.groupdict().get('tier')
    return CitedVerdict(tree=last['tree'], env=last['env'], tier=tier, result=last['result'].upper(), line=line)


def _describe(entry: Entry) -> str:
    return f'{entry.result} tier={entry.tier} {entry.test} tree={entry.tree} env={entry.env} evidence={entry.log}'


def admit(
    rows: Sequence[Entry],
    *,
    destination: str,
    trunk_tiers: Collection[str],
    head: str,
    clean: bool,
    env: str,
    gap: Path | None = None,
) -> Admission:
    """Decide a push to *destination* from the ledger's *rows*, by the table in this module's docstring.

    Only RUN-LEVEL entries naming *head* as their commit, in *env*, are citable; a per-test entry
    says nothing about a selection. PASS is preferred over FAIL, then the newest. Citing a FAIL
    writes the gap record at *gap* when one is named.
    """
    if destination == LANE:
        return Admission(
            allowed=True,
            cited=None,
            message=(
                '[admission] lane: admitted with no verdict -- ONE-RUN-AFTER-INTEGRATION: the main session '
                'merges every ready lane and runs the gate once on the integrated tree.'
            ),
        )
    results = RESULTS[destination]
    if not clean:
        return Admission(
            allowed=False,
            cited=None,
            message=(
                f'[admission] {destination}: push REFUSED -- the working tree is dirty, so no entry names it.\n'
                '[admission] Remedy: commit, then run the gate on the clean integrated tree.'
            ),
        )
    citable = [
        (order, row)
        for order, row in enumerate(rows)
        if row.test.startswith(_RUN_PREFIX)
        and row.commit
        and row.commit == head
        and row.env == env
        and row.result in results
        and (destination != TRUNK or row.tier in trunk_tiers)
    ]
    if not citable:
        bar = f'a PASS of tier {sorted(trunk_tiers)}' if destination == TRUNK else f'one of {sorted(results)}'
        return Admission(
            allowed=False,
            cited=None,
            message=(
                f'[admission] {destination}: push REFUSED -- no recorded verdict for HEAD {head} in env={env}.\n'
                f'[admission] Remedy: run the gate on THIS clean, integrated tree; this push needs {bar}.'
            ),
        )
    _order, cited = min(citable, key=lambda item: (_RANK[item[1].result], -item[0]))
    lines = [
        f'[admission] {destination}: cited {cited.result} -- push proceeds.',
        f'[admission] cited: {_describe(cited)}',
    ]
    if gap is not None and cited.result != 'PASS':
        record_gap(gap, cited, rows)
        lines.append(f'[admission] gap recorded at {gap}')
    return Admission(allowed=True, cited=cited, message='\n'.join(lines))


def record_gap(path: Path, cited: Entry, rows: Sequence[Entry]) -> Path:
    """Write (or REWRITE) the gap record a FAIL citation leaves; returns *path*.

    The consumer names the dated path; this owns the content: the cited entry and the failing node
    ids the ledger recorded for the same tree and env.
    """
    failing = sorted(
        {
            row.test
            for row in rows
            if (row.tree, row.env) == (cited.tree, cited.env)
            and row.result == 'FAIL'
            and not row.test.startswith(_RUN_PREFIX)
        }
    )
    body = [
        f'# Push gap: {cited.result} cited for commit {cited.commit}',
        '',
        f'- verdict: `{_describe(cited)}`',
        f'- failing node ids: {len(failing)}',
        *(f'  - `{node}`' for node in failing),
        '',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(body), encoding='utf-8')
    return path


def destination_of(remote_ref: str, policy: Policy) -> str:
    """:data:`INTEGRATION` for the declared integration branch, else :data:`LANE`; the trunk is the caller's."""
    return INTEGRATION if remote_ref == f'refs/heads/{policy.integration}' else LANE


def unpublished_merges(root: Path) -> tuple[str, ...]:
    """The merge commits reachable from HEAD and from no remote ref -- what this push publishes first.

    An UNBORN HEAD (a fresh repository before its first commit) reaches no commit, so it publishes
    no merge: the answer is empty, never a crash of the audit that asked.
    """
    born = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', '--verify', '--quiet', 'HEAD^{commit}'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )
    if born.returncode:
        return ()
    listed = subprocess.run(
        [_GIT, '-C', str(root), 'rev-list', '--merges', 'HEAD', '--not', '--remotes'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=True,
        timeout=_GIT_TIMEOUT_S,
    ).stdout
    return tuple(listed.split())


def merge_refusals(root: Path, merges: Sequence[str], roots: Sequence[str]) -> tuple[str, ...]:
    """Every unnamed or over-named deviation in *merges*; an audit that cannot read is one too."""
    try:
        return refusals(root, merges, roots=roots)
    except MergeAuditError as error:
        return (str(error),)


def _audit_message(problems: Sequence[str], where: str) -> str:
    return '\n'.join(
        [
            f'[admission] {where}: push REFUSED -- a merge lost or rewrote tests without naming them.',
            *(f'[admission]   {line}' for line in problems),
            (
                '[admission] Remedy: restore what the resolution dropped, or name each deviation in the merge '
                f'commit (amend it before its first push) as `{TRAILER}: <KIND> <test> -- <reason>`.'
            ),
        ]
    )


def _tree_state(root: Path) -> tuple[str, bool]:
    head = subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()
    dirty = status_paths(root)
    return head, dirty == ()


def _current_env() -> str:
    return env_key(env_manifest())


def main(argv: Sequence[str] | None = None) -> int:
    """``0`` admit, ``1`` refuse -- the CLI a consumer's pre-push hook delegates to."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.admission', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout being pushed')
    parser.add_argument('--remote-ref', required=True, help='the full remote ref being updated')
    parser.add_argument('--trunk-ref', required=True, help="the trunk ref (e.g. refs/heads/main), or 'none'")
    parser.add_argument('--trunk-tier', action='append', default=[], help='a tier whose PASS the trunk accepts')
    parser.add_argument('--ledger', type=Path, help="the verdict ledger (default: the main checkout's)")
    parser.add_argument('--gap', type=Path, help='where a FAIL citation records its gap (the consumer dates it)')
    args = parser.parse_args(argv)
    trunk = args.trunk_ref != 'none' and args.remote_ref == args.trunk_ref
    if trunk and not args.trunk_tier:
        parser.error('--trunk-tier is required when the push targets the trunk')
    policy = load_policy(args.root)
    destination = TRUNK if trunk else destination_of(args.remote_ref, policy)
    problems = merge_refusals(args.root, unpublished_merges(args.root), policy.test_roots)
    if problems:
        emit(_audit_message(problems, destination))
        return 1
    head, clean = _tree_state(args.root)
    ledger = args.ledger if args.ledger is not None else ledger_path(args.root)
    decided = admit(
        entries(ledger),
        destination=destination,
        trunk_tiers=args.trunk_tier,
        head=head,
        clean=clean,
        env=_current_env(),
        gap=args.gap,
    )
    emit(decided.message)
    return 0 if decided.allowed else 1


if __name__ == '__main__':
    raise SystemExit(main())
