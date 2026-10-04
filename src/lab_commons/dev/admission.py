"""PUSH ADMISSION -- the family's ONE answer to "may this push cite that verdict".

THE RULE (user ruling 2026-10-04, "INCONCLUSIVE may be pushed"):

=================  ======================================  =========================
destination        admitted results, same tree and env     refused
=================  ======================================  =========================
a lane / an        PASS, FAIL, INCONCLUSIVE                no verdict; another tree;
integration branch                                         another env; a dirty tree
the trunk          PASS of a trunk tier, nothing else      everything else
=================  ======================================  =========================

A lane push used to be refused on INCONCLUSIVE because "nothing was proved". That made origin -- the
only shared medium -- unreachable for exactly the increments too wide or too contended to judge, and
the refusal re-ran the same wall on every retry. The trunk is where the strict bar belongs, and it
keeps it. What travels on a lane instead is the GAP: citing a non-PASS verdict writes a record of
the verdict line, the failing node ids and the never-ran count at a dated path the consumer names,
so the gap is inventory someone can read rather than a push nobody could make.

WHY HERE AND NOT IN EACH CONSUMER. Three repos each carried a copy of this table and of the verdict
grammar it reads, and the copies disagreed (first versus last match, PASS-only versus PASS/FAIL).
:mod:`lab_commons.dev.famtests.localadmission` refuses a consumer that keeps one.

PUSH ADMISSION IS NOT STATUS PROMOTION. :mod:`lab_commons.dev.verify` PROMOTES a run out of
INCONCLUSIVE only on complete proof, and :mod:`lab_commons.dev.forgestatus` maps the result to a
forge state; neither changes here. This module only decides which recorded verdict a push may CITE.
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
from lab_commons.dev.logref import MARKER
from lab_commons.dev.treedirt import status_paths
from lab_commons.log import emit

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

__all__ = [
    'LANE_RESULTS',
    'TRUNK_RESULTS',
    'VERDICT_STAMP',
    'Admission',
    'CitedVerdict',
    'admit',
    'decide_fresh',
    'main',
    'parse_verdict_line',
    'record_gap',
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

LANE_RESULTS: Final = frozenset({'PASS', 'FAIL', 'INCONCLUSIVE'})
TRUNK_RESULTS: Final = frozenset({'PASS'})

#: Preference when several anchors are citable: the strongest statement about the tree wins.
_RANK: Final = {'PASS': 0, 'FAIL': 1, 'INCONCLUSIVE': 2}

#: A short stamp must still name a commit unambiguously enough to compare.
_MIN_SHA: Final = 7

_FAILED: Final = re.compile(r'^(?:FAILED|ERROR) (\S+)', re.MULTILINE)
_NEVER_RAN: Final = re.compile(r'(\d+) of \d+ asked NOT RUN')
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
    """The decision, the verdict it rests on, and the text the hook prints."""

    allowed: bool
    cited: CitedVerdict | None
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


def _same_tree(stamp: str, head: str) -> bool:
    return len(stamp) >= _MIN_SHA and len(head) >= _MIN_SHA and (head.startswith(stamp) or stamp.startswith(head))


def _why_not(
    cited: CitedVerdict | None,
    *,
    results: Collection[str],
    head: str,
    clean: bool,
    env: str | None,
) -> str | None:
    """``None`` when *cited* is admissible, else the reason in words a pusher can act on."""
    if cited is None:
        return 'no verdict'
    if cited.result not in results:
        return f'{cited.result} is not admitted here (needs one of {sorted(results)})'
    if not clean:
        return 'the working tree is dirty, so no stamp names it'
    if not _same_tree(cited.tree, head):
        return f'tree={cited.tree} is not HEAD {head}'
    if env is None or cited.env != env:
        return f'env={cited.env} is not this environment ({env})'
    return None


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None


def _announce(cited: CitedVerdict, *, where: str, gap: Path | None) -> str:
    lines = [f'[admission] {where}: cited {cited.result} -- push proceeds.', f'[admission] cited: {cited.line}']
    if cited.result == 'INCONCLUSIVE':
        lines += [
            '[admission] !!! INCONCLUSIVE CITED -- nothing was proved about this tree. The push proceeds',
            '[admission] !!! INCONCLUSIVE CITED -- because a lane may carry it; the trunk will not.',
        ]
    if gap is not None and cited.result != 'PASS':
        lines.append(f'[admission] gap recorded at {gap}')
    return '\n'.join(lines)


def admit(
    anchors: Sequence[tuple[str, Path]],
    *,
    trunk: bool,
    trunk_tiers: Collection[str],
    head: str,
    clean: bool,
    env: str | None,
    gap: Path | None = None,
) -> Admission:
    """Decide a push from recorded verdicts. *anchors* are ``(tier, path)`` in the repo's preference.

    A lane tries every anchor and cites the strongest admissible result (PASS over FAIL over
    INCONCLUSIVE, ties in anchor order); the trunk reads only *trunk_tiers* and only a PASS. A lane
    citing a non-PASS writes or refreshes the gap record at *gap* when one is named.
    """
    results = TRUNK_RESULTS if trunk else LANE_RESULTS
    where = 'trunk' if trunk else 'lane'
    admissible: list[tuple[int, int, CitedVerdict, str]] = []
    reasons: list[str] = []
    for order, (tier, path) in enumerate(anchors):
        if trunk and tier not in trunk_tiers:
            continue
        text = _read(path)
        cited = parse_verdict_line(text) if text is not None else None
        if cited is not None and cited.tier is not None and cited.tier != tier:
            cited_reason: str | None = f'the {tier} anchor holds a tier={cited.tier} verdict'
        else:
            cited_reason = _why_not(cited, results=results, head=head, clean=clean, env=env)
        if cited_reason is None and cited is not None and text is not None:
            admissible.append((_RANK[cited.result], order, cited, text))
        else:
            reasons.append(f'[admission]   {tier} ({path}): {cited_reason or "no verdict"}')
    if not admissible:
        bar = f'a PASS of tier {sorted(trunk_tiers)}' if trunk else 'a PASS, FAIL or INCONCLUSIVE verdict'
        message = '\n'.join(
            [
                f'[admission] {where}: push REFUSED -- no recorded verdict for tree={head} in env={env}.',
                *(reasons or ['[admission]   no anchor applies to this destination']),
                f'[admission] Remedy: run the gate on THIS clean tree; this push needs {bar}.',
            ]
        )
        return Admission(allowed=False, cited=None, message=message)
    _rank, _order, cited, text = min(admissible, key=lambda item: item[:2])
    if gap is not None and cited.result != 'PASS':
        record_gap(gap, cited, text)
    return Admission(allowed=True, cited=cited, message=_announce(cited, where=where, gap=gap))


def decide_fresh(log: Path, *, trunk: bool, gap: Path | None = None) -> Admission:
    """Decide a push from the log of a run made FOR this push, by the same table as :func:`admit`.

    No tree or env comparison: the run just judged this tree in this env. No log or no readable
    verdict is still a refusal -- that is a run that died before it could say anything.
    """
    where = 'trunk' if trunk else 'lane'
    text = _read(log)
    if text is None:
        return Admission(
            allowed=False, cited=None, message=f'[admission] {where}: the run wrote no log at {log} -- push REFUSED.'
        )
    cited = parse_verdict_line(text)
    if cited is None:
        return Admission(
            allowed=False, cited=None, message=f'[admission] {where}: no verdict readable in {log} -- push REFUSED.'
        )
    if cited.result not in (TRUNK_RESULTS if trunk else LANE_RESULTS):
        refused = f'[admission] trunk: {cited.result} -- push REFUSED; the trunk takes a PASS.'
        return Admission(allowed=False, cited=cited, message=f'{refused}\n[admission] cited: {cited.line}')
    if gap is not None and cited.result != 'PASS':
        record_gap(gap, cited, text)
    return Admission(allowed=True, cited=cited, message=_announce(cited, where=where, gap=gap))


def record_gap(path: Path, cited: CitedVerdict, log_text: str) -> Path:
    """Write (or REWRITE) the gap record a non-PASS citation leaves; returns *path*.

    The consumer names the dated path; this owns the content: the verdict line, the failing node ids
    read off the log's ``FAILED``/``ERROR`` lines, and the never-ran count when the log states one.
    """
    failing = sorted(set(_FAILED.findall(log_text)))
    never = _NEVER_RAN.findall(log_text)
    body = [
        f'# Push gap: {cited.result} cited for tree {cited.tree}',
        '',
        f'- verdict: `{cited.line}`',
        f'- never ran: {never[-1] if never else "unknown"}',
        f'- failing node ids: {len(failing)}',
        *(f'  - `{node}`' for node in failing),
        '',
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(body), encoding='utf-8')
    return path


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
    parser.add_argument(
        '--anchor', action='append', default=[], help='TIER=PATH of a recorded verdict, in preference order'
    )
    parser.add_argument('--fresh-log', type=Path, help='decide from the log of a run made for this push')
    parser.add_argument('--gap', type=Path, help='where a non-PASS citation records its gap (the consumer dates it)')
    args = parser.parse_args(argv)
    trunk = args.trunk_ref != 'none' and args.remote_ref == args.trunk_ref
    if trunk and not args.trunk_tier:
        parser.error('--trunk-tier is required when the push targets the trunk')
    if args.fresh_log is not None:
        decided = decide_fresh(args.fresh_log, trunk=trunk, gap=args.gap)
    else:
        anchors = []
        for spec in args.anchor:
            tier, sep, path = spec.partition('=')
            if not sep:
                parser.error(f'--anchor takes TIER=PATH, not {spec!r}')
            anchors.append((tier, args.root / path))
        head, clean = _tree_state(args.root)
        decided = admit(
            anchors, trunk=trunk, trunk_tiers=args.trunk_tier, head=head, clean=clean, env=_current_env(), gap=args.gap
        )
    emit(decided.message)
    return 0 if decided.allowed else 1


if __name__ == '__main__':
    raise SystemExit(main())
