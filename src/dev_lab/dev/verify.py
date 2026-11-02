"""The family's ONE verify entry point: ``python -m dev_lab.dev.verify``.

WHY IT IS HERE AND NOT IN A REPO. Four repos share this library, and exactly one of them --
consumer-a -- has an entry point that produces a :class:`~dev_lab.dev.verdict.Verdict`
(a 1770-line ``scripts/gate/runner.py`` that knows about cases, solvers and vendor engines, and
is not portable to a repo that has none of those). The other three have NOTHING, so an agent
working in one can only type a bare ``pytest`` line -- which the family's hooks deny, and they
deny it for the reason this module exists: a bare invocation returns an exit code, and an exit
code cannot say whether the run COVERED what it selected. This module is the portable remainder:
three steps, a log, and a verdict built out of the algebra in :mod:`dev_lab.dev.verdict` --
plus :data:`~dev_lab.dev.hook_install.HOOKS_STEP`, which fails the run when a hook the repo
declares is not installed.

THE POLARITY IS INHERITED, NOT RE-DECIDED. A run starts INCONCLUSIVE and is PROMOTED only on
proof. The measured case that motivates it is in that module's own docstring, and the parser that
catches it lives in :mod:`dev_lab.dev.reports` -- which is where every judgement about what a
step's output MEANS lives, so that this module can be about processes, logs and exit codes and
nothing else.

THE STEPS -- ruff check, ruff format --check, pytest in the box -- and the verdict they fold into are
:mod:`dev_lab.dev.verifysteps`; this module is the command around them: the cache, the box-wide run, the post.

EXIT CODES, and the two non-zero ones are DIFFERENT ON PURPOSE:

* ``0`` -- PASS. The proof held and nothing failed.
* ``1`` -- FAIL. The proof held and the failures are NAMED. Fix the code.
* ``3`` -- INCONCLUSIVE. The run cannot say. Re-run it, or fix what truncated it. A caller that
  collapses 1 and 3 has rebuilt the bug the verdict algebra exists to end.

``2`` stays argparse's refused argv: these are the producer exit contract (:mod:`dev_lab.dev.producer`).
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

import lab_commons.launch as _door
from lab_commons.box import POLL_S, Refused
from lab_commons.envkey import env_key, env_manifest
from lab_commons.hpc.needsets import BASE
from lab_commons.hpc.retired import refusal
from lab_commons.log import emit
from lab_commons.outcomes import Conclusion

from dev_lab.dev.content import content_address
from dev_lab.dev.forgeclaim import this_machine
from dev_lab.dev.forgerequest import offer_line
from dev_lab.dev.forgestatus import head_sha, verdict_commit
from dev_lab.dev.forgework import Client, client_for
from dev_lab.dev.inflight import RunKey, box_directory, run_once
from dev_lab.dev.localpart import part_selection, post_cited, post_part
from dev_lab.dev.lockpins import lock_freshness
from dev_lab.dev.lockwait import lock_wait_arg
from dev_lab.dev.logref import UnverifiableLog
from dev_lab.dev.platformparts import part_context
from dev_lab.dev.producer import ProducerExit, full_suite_refusal
from dev_lab.dev.reports import (
    MalformedAllowance,
)
from dev_lab.dev.runcache import cache_path, cached, remember
from dev_lab.dev.selection import is_targeted
from dev_lab.dev.treedirt import status_paths
from dev_lab.dev.verdictstore import ContentKey, Found
from dev_lab.dev.verifybox import (
    MEASURE_WAIT_S,
    WAIT_S,
)
from dev_lab.dev.verifysteps import MEASURED_TARGETS, run_verify
from dev_lab.dev.workstationverdict import after_run, before_run, head_tree, workstation_fields, workstation_refusal

__all__ = [
    'EXIT_CODES',
    'is_targeted',
    'main',
    'project_root',
    'run_key',
]

#: The process exit code each outcome maps to. FAIL and INCONCLUSIVE are distinct because their
#: remedies are distinct: one is "fix the code", the other is "nobody knows yet".
EXIT_CODES: Final[dict[Conclusion, int]] = {outcome: ProducerExit[outcome.name] for outcome in Conclusion}


def project_root(start: Path | None = None) -> Path:
    """The checkout this verify run is about, from ``git rev-parse --show-toplevel``.

    ASKED OF GIT rather than walked up looking for a marker file. A marker walk finds the nearest
    directory holding a ``pyproject.toml``, which inside a monorepo or a nested package is a
    DIFFERENT tree from the one a reader would check -- and an address computed against the wrong
    root is a verdict about a repo nobody ran.

    Raises:
        SystemExit: *start* is not inside a git checkout, or git is not installed. Refused rather
            than guessed: every field of a verdict is anchored to this path, so a fallback root
            would produce a well-formed verdict about the wrong tree.

    """
    try:
        found = _door.run(
            ['git', 'rev-parse', '--show-toplevel'],
            cwd=start or Path.cwd(),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = exc.stderr.strip() if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        msg = (
            f'verify could not find a git checkout at {start or Path.cwd()}: {detail or exc}. Every '
            f'field of a verdict -- the tree address, the log, the paths the steps run over -- is '
            f'anchored to the repository root, so there is nothing to verify until this resolves.'
        )
        raise SystemExit(msg) from exc
    return Path(found.stdout.strip()).resolve()


def main(argv: list[str] | None = None) -> int:
    """``python -m dev_lab.dev.verify [-- pytest args]``. Returns the process exit code.

    Output goes through :func:`lab_commons.log.emit` rather than ``print``: this family never
    waives ruff's T201, and ``emit`` is the shared one-line idiom that exists for exactly this --
    a CLI tool whose stdout IS the product. No module in ``lab_commons`` calls ``print``, and this
    one does not become the first.

    A :class:`~dev_lab.dev.reports.MalformedAllowance` is turned into a one-line refusal here
    rather than allowed to reach the terminal as a traceback: the reader of that message is the
    person who typed the declaration, and a stack trace tells them about this module instead. It
    exits INCONCLUSIVE, because nothing was measured.

    :class:`~lab_commons.box.Refused` -- the environment seat held, or no room in the box -- takes one
    route, with one exit code: nothing was measured, and INCONCLUSIVE is what a run that cannot say is
    required to say. The line NAMES the holder and the remedy, because "busy" sends its reader to the
    process table to guess and guessing wrong kills somebody's evidence.

    ONLY THE PRODUCER POSTS (VERDICTS-FROM-THE-FORGE): a run inside the process ``forge serve`` spawned for
    this part (:func:`~dev_lab.dev.producer.full_suite_refusal` answers ``None``) posts its settled run;
    any other run -- a developer's or an agent's targeted measure -- is never a verdict and posts NOTHING.
    Measured 2026-10-17/18: local measures posted ``tests/base`` on integrate/main shas 911a9f8, 1299048
    and 6b34c738b156, a partial selection claiming a whole part.

    A PRODUCER'S SETTLED RUN IS POSTED AS PARTS, ``tests/<part>`` -- one per need-set
    (:mod:`dev_lab.dev.platformparts`): its per-test outcomes become run records of the cluster's
    shape (scope ``full`` for a bare run, ``incremental`` for a selection), posted on HEAD only when the
    tree was clean before and after the run and HEAD did not move. ``--part <part>`` is the declared
    producer's form: it runs EXACTLY that part's need-set (:func:`lab_commons.hpc.needsets.selecting`) and
    posts that part alone; a bare run posts every part it judged whose needs this host has
    (:func:`dev_lab.dev.localpart.post_part`). An INCONCLUSIVE run is no part and posts nothing.
    A refused or failed post is one line; it changes neither the verdict nor
    the exit code.
    """
    parser = argparse.ArgumentParser(
        prog='python -m dev_lab.dev.verify',
        description='Run ruff check, ruff format --check and pytest, and print a citable verdict.',
        epilog='Exit codes: 0 pass, 1 fail (failures named), 2 refused argv, 3 inconclusive (the run cannot say).',
    )
    parser.add_argument(
        '--lock-wait',
        type=lock_wait_arg,
        default=None,
        metavar='DURATION',
        help=(
            f'ceiling on the wait for this box, a duration such as "30 s" (default {MEASURE_WAIT_S:.0f} s for a '
            f'selection, {WAIT_S:.0f} s for the producer); "0 s" checks once and refuses'
        ),
    )
    parser.add_argument('--part', default='', help='produce this part (tests/<part>): exactly its need-set')
    parser.add_argument('--rerun', action='store_true', help='run even when the run cache already judged this key')
    parser.add_argument('pytest_args', nargs='*', help='extra arguments forwarded to pytest, after a bare --')
    if retired := _retired(sys.argv[1:] if argv is None else argv):
        emit(retired, err=True)
        return ProducerExit.USAGE
    parsed = parser.parse_args(argv)
    root = project_root()
    arguments = tuple(parsed.pytest_args)
    targeted = is_targeted(root, arguments)
    outside, workstation = _outside(root, parsed.part, arguments, targeted=targeted)
    refused = None if targeted else outside
    try:
        posted, arguments = arguments, (*part_selection(root, parsed.part), *arguments)
    except ValueError as why:
        refused = refused or f'verify: refused -- {why}'
    if refused is not None:
        emit(refused, err=True)
        return ProducerExit.USAGE
    wait_s = parsed.lock_wait if parsed.lock_wait is not None else (MEASURE_WAIT_S if targeted else WAIT_S)
    stale = lock_freshness(root)
    if stale:
        emit(f'verify: inconclusive -- nothing ran: {stale}', err=True)
        return EXIT_CODES[Conclusion.INCONCLUSIVE]
    key = run_key(root, arguments)
    cache = cache_path(root)
    cited = None if parsed.rerun else cached(cache, tree=key.tree, env=key.env, selector=key.selector)
    if cited is not None:
        emit(
            f'verify: CITED {cited.result} -- the run cache ({cache}) already judged this tree, env and selection; '
            f'evidence: {cited.log}. Nothing ran; --rerun runs it again.'
        )
        _post_cited(root, cited.log, posted, part=parsed.part, producer=outside is None)
        return EXIT_CODES[Conclusion(cited.result.lower())]

    post = None
    if outside is None:
        post = functools.partial(post_part, root, arguments=posted, part=parsed.part, extra=workstation)
    stored, check = _stored(root, parsed.part, key, producer=post is not None and not posted and not parsed.rerun)
    if stored is not None and check is None:
        return EXIT_CODES[stored.result]
    code = _lead(root, arguments, key, cache, wait_s=wait_s, post=post)
    if stored is not None and check is not None:
        emit(after_run(check, stored, _CONCLUSION_OF.get(code, Conclusion.INCONCLUSIVE)))
    return code


def _lead(
    root: Path, arguments: tuple[str, ...], key: RunKey, cache: Path, *, wait_s: float, post: Callable[..., str] | None
) -> int:
    """Run *key* once across the box -- leading it, or attaching to the run in flight; the exit code."""

    def lead() -> str:
        code, lines = _judge(root, arguments, key, cache, wait_s=wait_s, post=post)
        return json.dumps({'code': code, 'lines': lines})

    answer, attached = run_once(key, lead, directory=box_directory(), poll_s=POLL_S)
    shared = json.loads(answer)
    if attached:
        emit('verify: ATTACHED to the run already in flight for this tree, env and selection; its answer:')
        for line in shared['lines']:
            emit(line)
    return int(shared['code'])


def _outside(root: Path, part: str, arguments: tuple[str, ...], *, targeted: bool) -> tuple[str | None, dict[str, str]]:
    """``(the full-suite refusal or None, a declared workstation's record keys)`` for this run.

    THE ONE EXCEPTION (ruling D50-1): outside a producer, a ``--part`` run is admitted when this box is a declared
    workstation posting the full part of a clean pushed tree (:mod:`dev_lab.dev.workstationverdict`); else the
    refusal names why it is not, beside the remedy.
    """
    outside = full_suite_refusal('verify', os.environ, part_context(part or BASE))
    if outside is None or not part or targeted:
        return outside, {}
    why = workstation_refusal(root, part, full=not arguments)
    return (None, workstation_fields(root)) if why is None else (f'{outside} Or: {why}.', {})


#: The conclusion an exit code says (the inverse of :data:`EXIT_CODES`).
_CONCLUSION_OF: Final = {code: conclusion for conclusion, code in EXIT_CODES.items()}


def _stored(root: Path, part: str, key: RunKey, *, producer: bool) -> tuple[Found | None, Client | None]:
    """A *producer*'s dedupe of its full *part* by content key (:mod:`dev_lab.dev.workstationverdict`).

    ``(found, None)``: *found* was CITED on HEAD -- nothing runs. ``(found, client)``: a spot check -- run, then
    compare. ``(None, None)``: no producer of a full part, no hit, or the forge or HEAD unreadable -- run.
    """
    sha, tree = (head_sha(root), head_tree(root)) if producer and part else ('', '')
    if not sha or not tree:
        return None, None
    try:
        client = client_for(root)
    except OSError:
        return None, None
    decision = before_run(root, sha, ContentKey(tree, key.env, part), me=this_machine(), client=client)
    if decision.line:
        emit(decision.line)
    if decision.found is None:
        return None, None
    return decision.found, (None if decision.cited else client)


def _post_cited(root: Path, log: str, posted: tuple[str, ...], *, part: str, producer: bool) -> None:
    """The PRODUCER's cited run posts from its own outcomes, beside *log*; nothing re-runs, and nobody else posts."""
    if producer:
        emit(post_cited(root, log, posted, head=head_sha(root), dirt=status_paths(root), part=part))


def _retired(argv: list[str]) -> str | None:
    """The refusal of the first retired word in *argv* (:mod:`lab_commons.hpc.retired`), else ``None``."""
    return next(filter(None, (refusal('verify', word) for word in argv)), None)


def run_key(root: Path, pytest_args: tuple[str, ...]) -> RunKey:
    """What makes two verify requests ONE run: the tree address, the env key and the selection."""
    return RunKey(
        tree=content_address(root, MEASURED_TARGETS),
        env=env_key(env_manifest()),
        selector=' '.join(('verify', *pytest_args)),
    )


def _inconclusive(line: str) -> tuple[int, list[str]]:
    """A run that measured nothing: *line* to stderr, the INCONCLUSIVE exit code, and the line it printed."""
    emit(line, err=True)
    return EXIT_CODES[Conclusion.INCONCLUSIVE], [line]


def _judge(
    root: Path, arguments: tuple[str, ...], key: RunKey, cache: Path, *, wait_s: float, post: Callable[..., str] | None
) -> tuple[int, list[str]]:
    """The leader's run: judge, stamp, cache, post the parts, and return the exit code with the lines it printed.

    *arguments* is what pytest ran; *post* posts the parts (``None``: not the producer).
    """
    head, start = head_sha(root), status_paths(root)
    try:
        verdict = run_verify(root, arguments, wait_s=wait_s, hooks=post is None)
    except MalformedAllowance as exc:
        return _inconclusive(f'verify refuses to run: {exc}')
    except Refused as exc:  # CAPACITY, never a verdict: a producer's claim goes back to claimable (UNREACHABLE)
        code, lines = _inconclusive(
            f'verify: inconclusive -- this box is held and nothing was measured. Held by: {exc}. '
            f'Wait for it, or stop that holder, then re-run; '
            f'--lock-wait "<duration>" raises or drops the {wait_s:.0f} s ceiling on the wait. '
            f'{offer_line(root, head, arguments)}'
        )
        return (ProducerExit.UNREACHABLE if post is not None else code), lines
    except UnverifiableLog as exc:
        return _inconclusive(
            f'verify: inconclusive -- the run wrote no usable log ({exc}); fix what emptied it, then re-run.'
        )
    verdict.stamp()
    lines = [verdict.line(), f'verify: {verdict.result.render()}']
    lines += [f'  failed: {failure}' for failure in verdict.result.failures]
    emit('')
    for line in lines:
        emit(line)
    commit = verdict_commit(head, head_sha(root), start, status_paths(root))
    if run_key(root, ()).tree == key.tree:
        remember(cache, verdict, tree=key.tree, env=key.env, selector=key.selector, commit=commit or '')
    if post is not None:
        emit(post(verdict.log.path, commit, settled=verdict.result.outcome.settled))
    return EXIT_CODES[verdict.result.outcome], lines


if __name__ == '__main__':
    raise SystemExit(main())
