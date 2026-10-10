"""PUSH ADMISSION -- the family's ONE answer to "may this push go", read off the FORGE.

THE RULE (user rulings 2026-10-04, 2026-10-08 and 2026-10-09, forge plan section 6):

==================  ================================================  ===============================
destination         admitted                                          refused
==================  ================================================  ===============================
a lane              always -- a lane carries no result of its own      nothing
an integration ref  always -- parts are produced FROM pushed shas      nothing
the trunk           every required part of HEAD is a ``full`` PASS    anything else, or the forge down
==================  ================================================  ===============================

PARTS ARE PRODUCED FROM PUSHED SHAS. A pushed integration sha lacking its parts IS the request
(:mod:`lab_commons.dev.forgetick`), so an integration push cannot wait for parts that only its push
makes possible. The trunk is where everything must already be green: HEAD's ``tests/<platform>``
statuses (:mod:`lab_commons.dev.platformparts`) are read from the forge and composed -- every part a
PASS of scope ``full``, every platform some part hands ids to present, no id runnable nowhere. An
incremental part is a re-run of named ids and says nothing about the rest, so it is not a trunk part.

THE FORGE IS THE ONE SOURCE, AND THERE IS NO LOCAL FALLBACK. The run cache is this box's memory of
its verify runs (:mod:`lab_commons.dev.runcache`) and decides no push: a result only this box can see is
a result no other workstation can check. If the forge cannot be read, the trunk WAITS --
the refusal names the remedy; nothing local stands in for it.

EVERY DESTINATION AUDITS THE MERGES IT PUBLISHES, unconditionally: each merge commit not yet on any
remote must name every test its resolution lost or rewrote (:mod:`lab_commons.dev.mergeaudit`).

THE STAMP GRAMMAR'S READER STAYS HERE. Runners still stamp their logs (``[verdict tree= env= tier=
selector=] RESULT`` and :mod:`lab_commons.dev.verify`'s flat line) as the evidence a ledger entry
points at, and :func:`parse_verdict_line` is the one reader of both. It does not decide a push.

WHY HERE AND NOT IN EACH CONSUMER. Three repos each carried a copy of this table and the copies
disagreed. :mod:`lab_commons.dev.famtests.localadmission` refuses a consumer that keeps one.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from lab_commons.dev.forge import _GIT, NoCredential, UnreadableRemote
from lab_commons.dev.forgeoutbox import unprompted_client
from lab_commons.dev.forgestatus import Status, status_list
from lab_commons.dev.forgework import ForgeCallFailed
from lab_commons.dev.lanepolicy import Policy, load_policy
from lab_commons.dev.logref import MARKER
from lab_commons.dev.mergeaudit import TRAILER, MergeAuditError, refusals
from lab_commons.dev.platformparts import standing
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

__all__ = [
    'INTEGRATION',
    'LANE',
    'TRUNK',
    'TRUNK_SCOPE',
    'VERDICT_STAMP',
    'Admission',
    'CitedVerdict',
    'admit',
    'destination_of',
    'main',
    'merge_refusals',
    'parse_verdict_line',
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

#: The one scope whose parts the trunk admits: every id, not a re-run of named ones.
TRUNK_SCOPE: Final = 'full'

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
    """The decision and the text the hook prints."""

    allowed: bool
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


def admit(destination: str, *, head: str, statuses: Callable[[], Sequence[Status]]) -> Admission:
    """Decide a push to *destination* by the table in this module's docstring.

    *statuses* reads HEAD's latest status per context from the forge; it is called only for the trunk,
    and any failure to read is a refusal (the trunk waits), never a pass.
    """
    if destination in {LANE, INTEGRATION}:
        return Admission(
            allowed=True,
            message=(
                f'[admission] {destination}: admitted with no part -- parts are produced from pushed shas; '
                'only the trunk needs every part green.'
            ),
        )
    try:
        found = tuple(statuses())
    except (ForgeCallFailed, NoCredential, UnreadableRemote, OSError) as exc:
        return Admission(
            allowed=False,
            message=(
                f'[admission] trunk: push REFUSED -- the forge could not be read for HEAD {head} ({exc}).\n'
                '[admission] Remedy: the trunk WAITS for the forge; there is no local fallback. Retry once '
                '`python -m lab_commons.dev.forge status list <sha>` answers.'
            ),
        )
    judged = standing(found, head=head, scope=TRUNK_SCOPE)
    cited = judged.cited()
    if judged.result != 'PASS':
        problems = judged.problems or tuple(f'{part.platform} is {part.result}' for part in judged.parts)
        return Admission(
            allowed=False,
            message='\n'.join(
                [
                    f'[admission] trunk: push REFUSED -- the parts of HEAD {head} on the forge ({cited or "none"}):',
                    *(f'[admission]   {problem}' for problem in problems),
                ]
            ),
        )
    return Admission(allowed=True, message=f'[admission] trunk: every part of HEAD {head} is green ({cited}).')


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


def _head(root: Path) -> str:
    return subprocess.run(
        [_GIT, '-C', str(root), 'rev-parse', 'HEAD'],
        capture_output=True,
        text=True,
        encoding='utf-8',
        check=False,
        timeout=_GIT_TIMEOUT_S,
    ).stdout.strip()


def main(argv: Sequence[str] | None = None) -> int:
    """``0`` admit, ``1`` refuse -- the CLI a consumer's pre-push hook delegates to."""
    parser = argparse.ArgumentParser(prog='python -m lab_commons.dev.admission', description=__doc__.splitlines()[0])
    parser.add_argument('--root', type=Path, default=Path.cwd(), help='the checkout being pushed')
    parser.add_argument('--remote-ref', required=True, help='the full remote ref being updated')
    parser.add_argument('--trunk-ref', required=True, help="the trunk ref (e.g. refs/heads/main), or 'none'")
    argv = sys.argv[1:] if argv is None else list(argv)
    for word in argv:
        if refused := refusal('admission', word.split('=', 1)[0]):
            parser.error(refused)
    args = parser.parse_args(argv)
    trunk = args.trunk_ref != 'none' and args.remote_ref == args.trunk_ref
    policy = load_policy(args.root)
    destination = TRUNK if trunk else destination_of(args.remote_ref, policy)
    problems = merge_refusals(args.root, unpublished_merges(args.root), policy.test_roots)
    if problems:
        emit(_audit_message(problems, destination))
        return 1
    head = _head(args.root)
    decided = admit(destination, head=head, statuses=lambda: status_list(unprompted_client(args.root), head))
    emit(decided.message)
    return 0 if decided.allowed else 1


if __name__ == '__main__':
    raise SystemExit(main())
