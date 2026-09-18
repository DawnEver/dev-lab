"""The family's ONE verify entry point: ``python -m lab_commons.dev.verify``.

WHY IT IS HERE AND NOT IN A REPO. Four repos share this library, and exactly one of them --
motronics-studio -- has an entry point that produces a :class:`~lab_commons.dev.verdict.Verdict`
(a 1770-line ``scripts/gate/runner.py`` that knows about cases, solvers and vendor engines, and
is not portable to a repo that has none of those). The other three have NOTHING, so an agent
working in one can only type a bare ``pytest`` line -- which the family's hooks deny, and they
deny it for the reason this module exists: a bare invocation returns an exit code, and an exit
code cannot say whether the run COVERED what it selected. This module is the portable remainder:
three steps, a log, and a verdict built out of the algebra in :mod:`lab_commons.dev.verdict`.

THE POLARITY IS INHERITED, NOT RE-DECIDED. A run starts INCONCLUSIVE and is PROMOTED only on
proof. The measured case that motivates it is in that module's own docstring, and the parser that
catches it lives in :mod:`lab_commons.dev.reports` -- which is where every judgement about what a
step's output MEANS lives, so that this module can be about processes, logs and exit codes and
nothing else.

EVERY STEP RUNS, EVEN AFTER ONE FAILS, and that is a polarity decision rather than a convenience.
``make verify`` chains ``lint fmt-check test`` and stops at the first red, so a lint error leaves
the suite UNRUN -- and a caller reading that as "verify failed" has merged "the tests are red" with
"nobody knows whether the tests are red". Here an unrun step would be SILENT in the proof and would
drag the verdict to INCONCLUSIVE, so all three run and the verdict names the ones that failed.

EXIT CODES, and the two non-zero ones are DIFFERENT ON PURPOSE:

* ``0`` -- PASS. The proof held and nothing failed.
* ``1`` -- FAIL. The proof held and the failures are NAMED. Fix the code.
* ``2`` -- INCONCLUSIVE. The run cannot say. Re-run it, or fix what truncated it. A caller that
  collapses 1 and 2 has rebuilt the bug the verdict algebra exists to end.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final

from lab_commons.dev.boxwait import WAIT_S, hold_the_box, holders_line
from lab_commons.dev.content import content_address
from lab_commons.dev.envkey import env_key, env_manifest
from lab_commons.dev.logref import LogRef, UnverifiableLog
from lab_commons.dev.reports import MalformedAllowance, StepReport, declared_skips, read_pytest, read_ruff
from lab_commons.dev.verdict import Outcome, Proof, Result, Selector, Verdict
from lab_commons.log import emit
from lab_commons.resources import DEFAULT_POLL_S, Exhausted

__all__ = [
    'EXIT_CODES',
    'LOG_DIRECTORY',
    'MEASURED_TARGETS',
    'PYTEST_ARGS',
    'RUFF_STEPS',
    'build_verdict',
    'main',
    'project_root',
    'run_verify',
]

#: What the tree address covers, for EVERY repo in the family. A fixed tuple rather than a
#: per-repo list: :func:`~lab_commons.dev.content.content_address` records a target that is not
#: there as ``absent``, so a repo without one of these addresses differently instead of needing a
#: branch here -- and a repo that ACQUIRES one changes its address, which is correct.
MEASURED_TARGETS: Final[tuple[str, ...]] = ('src', 'tests', 'pyproject.toml')

#: Where the log lives. Under the project root rather than a platform cache dir, because the log
#: IS the evidence a verdict cites and a reader who was handed the tree must be able to find it.
LOG_DIRECTORY: Final = '.verify'

#: The two lint steps, in order, as ``(name, module args)``. Both run through ``sys.executable -m``
#: so the ruff that judges is the ruff installed in the interpreter that will run the suite -- a
#: bare ``ruff`` on ``PATH`` can be a different version from the one the ``dev`` extra resolved,
#: and a verdict carrying an env key must have been earned under that env.
RUFF_STEPS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ('ruff check .', ('ruff', 'check', '.')),
    ('ruff format --check .', ('ruff', 'format', '--check', '.')),
)

#: What pytest is always given, before anything the caller forwards. None of these three letters is
#: cosmetic; each one makes pytest NAME something it would otherwise only COUNT, and every check in
#: :mod:`lab_commons.dev.reports` compares names against names. A caller's own ``-r`` adds to the
#: report set rather than replacing it, so forwarding one cannot silence any of them.
#:
#:   ``s``  skips, for the two-sided skip ratchet, which cannot be checked against a number.
#:   ``f``  FAILURES. **Added 2026-09-16, and its absence was a real defect rather than a missing
#:          nicety.** With ``-rs`` alone pytest prints no ``FAILED`` line at all, so
#:          :func:`~lab_commons.dev.reports.read_pytest` saw a summary claiming N failures beside
#:          ZERO named node ids, fired its own disagreement check, and reported INCONCLUSIVE. Every
#:          red run in every repo would have come back "nobody knows" instead of "these tests
#:          failed" -- which is precisely the merge this module's docstring says must never happen,
#:          committed by the module that forbids it. MEASURED on optimi-lab: `2 failed, 130 passed`
#:          read as `inconclusive ... the summary names 2 failure(s) and the output names 0 node
#:          id(s)`.
#:   ``E``  ERRORS, for the same reason one letter over: an errored test is not a failed one, and a
#:          count of errors with no names attached is a shortfall nobody can act on.
#:
#: The disagreement check that caught this is kept exactly as it is. It was right -- the summary and
#: the named set genuinely disagreed -- and it is what turned a silent mis-classification into a
#: loud refusal. The bug was never the check; it was asking pytest for less than the check needs.
PYTEST_ARGS: Final[tuple[str, ...]] = ('-rfEs',)

#: The process exit code each outcome maps to. FAIL and INCONCLUSIVE are distinct because their
#: remedies are distinct: one is "fix the code", the other is "nobody knows yet".
EXIT_CODES: Final[dict[Outcome, int]] = {Outcome.PASS: 0, Outcome.FAIL: 1, Outcome.INCONCLUSIVE: 2}

#: ONE CSI escape, in ECMA-48's own grammar: ``ESC [``, then any number of PARAMETER bytes
#: (``0x30``-``0x3f``), then any number of INTERMEDIATE bytes (``0x20``-``0x2f``), then exactly one
#: FINAL byte (``0x40``-``0x7e``). SPELT OUT rather than written as "ESC and then whatever": a
#: pattern that eats anything after an ``ESC`` eats real content the first time a test prints one,
#: and ``\x1b\[[^m]*m`` -- the usual shorthand -- leaves every cursor-motion and erase-line sequence
#: in the text while claiming to have cleaned it. A LONE ``ESC``, and an ``ESC`` followed by anything
#: that is not this grammar, match nothing here and survive byte for byte.
_CSI: Final = re.compile(r'\x1b\[[\x30-\x3f]*[\x20-\x2f]*[\x40-\x7e]')

#: The line that separates the ruff half of the log from the pytest half. The pytest parser is fed
#: what comes AFTER it and never the whole log, because ruff's own output can carry a ``FAILED``
#: line or a count, and a parser handed both halves would attribute one step's words to the other.
_PYTEST_BANNER: Final = '--- pytest ---\n'


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
        found = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],  # noqa: S607 -- git is resolved through PATH on purpose
            cwd=start or Path.cwd(),
            capture_output=True,
            text=True,
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


def _tee(command: list[str], *, cwd: Path, handle: IO[str]) -> int:
    r"""Run *command*, streaming its merged output to *handle* AND to this process's stdout.

    STREAMED rather than captured and written afterwards, so a step that hangs still leaves in the
    log what it had printed when somebody killed it -- and so a step that is merely SLOW shows
    progress while it runs, which is the property this function is measured against.

    MEASURED 2026-09-16, on wdg-lab: a run sat 26+ minutes with nothing in its log but the two ruff
    lines while pytest was genuinely working the whole time, and the log's mtime was frozen. Two
    defects stacked to produce that, and both are fixed here rather than one:

    * this function wrote each line to *handle* but called ``handle.flush()`` only once, AFTER the
      loop -- so every line sat in Python's own buffered-file object until the subprocess exited,
      whatever the file was opened with. Flushing *handle* (and the console stream, via ``emit``'s
      own ``flush=True``) on every line is what makes the log's mtime move while the step runs.
    * the CHILD's stdout is fully block-buffered whenever it is not a real terminal, which a pipe
      never is -- pytest does not override this, so its own progress dots and ``-v`` lines sat in
      ITS buffer regardless of how eagerly this function read from the pipe. ``PYTHONUNBUFFERED=1``
      in the child's environment is the fix on the FAR side of the pipe; it is set on every process
      this function launches, not only the CPython ones, so a native tool that respects it benefits
      too and one that does not is unaffected.

    ``PYTHONIOENCODING=utf-8`` is set for the same reason the encoding below is NAMED: this function
    DECLARES the pipe carries utf-8, and on Windows a child writing to a pipe otherwise encodes in
    the locale codepage (cp1252 here), which makes that declaration false. MEASURED 2026-09-18: a
    child printing U+2713 into this pipe died of its OWN ``UnicodeEncodeError`` before a byte
    arrived, and a child that survives one sends bytes this end then mis-decodes. Naming the
    encoding on BOTH sides is what keeps ``errors='replace'`` a last resort rather than the normal
    path -- it is the consumer's hand-set ``PYTHONIOENCODING=utf-8`` workaround, absorbed.

    ``stderr`` is merged into ``stdout`` because a reader reconstructing what happened needs the two
    INTERLEAVED -- a separated stderr puts every ruff diagnostic after every line of pytest output,
    in an order that never occurred.

    ANSI COLOUR IS STRIPPED HERE, AT THE ONE POINT WHERE THE THREE READERS HAVE NOT YET DIVERGED,
    and that placement is the decision rather than the regex. MEASURED 2026-09-18: pytest under
    ``--color=yes`` (or ``FORCE_COLOR`` in a repo's ``addopts``) prints
    ``'\x1b[31mFAILED\x1b[0m test_c.py::\x1b[1mtest_a\x1b[0m - assert 0'``, and
    :data:`~lab_commons.dev.reports._FAILED_NODE` is anchored at ``^(?:FAILED|ERROR)`` -- so a
    genuine red came back ``the summary names 1 failure(s) and the output names 0 node id(s)``, an
    INCONCLUSIVE nobody can act on. The direction was safe, which is exactly why it went unnoticed;
    the cost is that no red is diagnosable in any repo that colours its output.

    LOOSENING THE ANCHOR WOULD NOT HAVE FIXED IT. The node id in that line is itself wrapped
    (``test_c.py::\x1b[1mtest_a\x1b[0m``), so ``(\S+)`` would have captured a node id with escapes
    inside it -- a FAIL naming a test that does not exist, which is worse than the refusal. The text
    has to be plain before any parser looks at it.

    ONE TEXT, THREE READERS, and that is why this is not done in the parser. ``50bf819`` settled that
    the utf-8 LOG is the citable evidence (``log=sha256:...@lines``, quoted across four repos) and the
    console is a VIEW of it. A parser-side strip would make the thing JUDGED a different text from the
    thing CITED: the sha256 would cover bytes the verdict never read, and a reader who greps
    ``FAILED`` in that log six months from now would MISS the very lines the verdict named -- the
    parser's defect, handed to the human. So the log LOSES the escapes. They are a statement about a
    terminal that will never render this file again, not about what happened, and the only reader who
    ever wanted them is the one nobody has: a ``cat`` back to a tty. What the reader gains is a log a
    plain ``grep -c '^FAILED'`` can count.

    The console loses them too, because it is a view of that text and a view that disagrees with its
    evidence is the same defect one layer up. The VIEW is what degrades, again.

    A LONE CARRIAGE RETURN IS LEFT ALONE. Universal-newline translation already splits a progress
    bar into lines -- ugly in a log, never fatal to a parse -- and :data:`_CSI` cannot match it.
    """
    handle.write(f'$ {" ".join(command)}\n')
    handle.flush()
    env = os.environ | {'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'}
    with subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding='utf-8',
        errors='replace',
        bufsize=1,
        env=env,
    ) as process:
        for raw in process.stdout or ():
            line = _CSI.sub('', raw)
            handle.write(line)
            handle.flush()
            emit(line.rstrip('\n'), flush=True)
    return process.returncode


def build_verdict(reports: tuple[StepReport, ...], *, tree: str, env: str, spec: str, log: LogRef) -> Verdict:
    """Fold the step reports into ONE verdict over the whole verify run.

    THE SELECTOR IS THE STEPS, and it is built from the step NAMES rather than from what they
    reported -- which is the only way ``silent`` can mean anything. A step that never launched
    contributes its name to ``selected`` and nothing to ``reported``, so it shows up BY NAME in the
    shortfall instead of quietly reducing the size of the run.

    Promotion is not decided here and cannot be: this hands the proof and the observed failures to
    :meth:`~lab_commons.dev.verdict.Result.settled`, which refuses PASS or FAIL over an incomplete
    proof. The branch below reads that proof rather than second-guessing it, so the only path to a
    settled result runs through the algebra's own guard.
    """
    selected = tuple(dict.fromkeys([report.name for report in reports] + [n for r in reports for n in r.reported]))
    selector = Selector(spec=spec, node_ids=selected)
    proof = Proof.of(
        selector,
        [name for report in reports for name in report.reported],
        truncated=[reason for report in reports for reason in report.truncated],
    )
    if proof.complete:
        result = Result.settled(proof=proof, failures=[name for report in reports for name in report.failures])
    else:
        result = Result.inconclusive(proof.refusal, proof=proof)
    return Verdict(tree=tree, env=env, selector=selector, result=result, log=log)


def run_verify(
    root: Path,
    pytest_args: tuple[str, ...] = (),
    *,
    wait_s: float = WAIT_S,
    poll_s: float = DEFAULT_POLL_S,
) -> Verdict:
    """Run the three steps under *root*, tee them into a fresh log, and return the verdict.

    The skip allowance is read BEFORE any step launches, so a declaration nobody can parse is
    refused against a tree that has not yet spent twenty minutes being tested.

    THE BOX IS HELD ACROSS ALL THREE STEPS and not only pytest, because the measured harm was 194
    CPU-minutes of a process TREE and ruff over a large tree is not free either.

    IT IS TAKEN AFTER :func:`~lab_commons.dev.reports.declared_skips` AND NOT BEFORE, which is the
    one place this departs from the plan it implements. That call is documented to run before any
    step launches so an unparseable declaration is refused against a tree that has not yet spent
    twenty minutes being tested; acquiring first would make the same refusal arrive up to thirty
    minutes later, having queued for a box it was never going to use.

    Raises:
        MalformedAllowance: ``[tool.lab_commons.verify] allowed_skips`` is present and unreadable.
        Exhausted: the box was held by another run for the whole of *wait_s*. Nothing was measured,
            so there is no verdict to return; :func:`main` renders it as INCONCLUSIVE.
        SystemExit: the log came out empty or unreadable, so no verdict may rest on it.
            :class:`~lab_commons.dev.logref.LogRef` refuses an empty log, and this refuses with it
            rather than stamping a verdict whose evidence says nothing -- the two are the same
            decision, made once, where the log is written.

    """
    allowed = declared_skips(root)
    directory = root / LOG_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'verify-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}.log'
    reports: list[StepReport] = []
    with contextlib.ExitStack() as box, path.open('w', encoding='utf-8') as handle:
        hold_the_box(box, f'verify:{root.name}', wait_s=wait_s, poll_s=poll_s)
        for name, arguments in RUFF_STEPS:
            reports.append(read_ruff(name, _tee([sys.executable, '-m', *arguments], cwd=root, handle=handle)))
        handle.write(_PYTEST_BANNER)
        code = _tee([sys.executable, '-m', 'pytest', *PYTEST_ARGS, *pytest_args], cwd=root, handle=handle)
    whole = path.read_text(encoding='utf-8', errors='replace')
    reports.append(read_pytest(whole.rpartition(_PYTEST_BANNER)[2], returncode=code, allowed_skips=allowed))
    try:
        log = LogRef.of(path)
    except UnverifiableLog as exc:
        msg = f'verify wrote no usable log: {exc}'
        raise SystemExit(msg) from exc
    return build_verdict(
        tuple(reports),
        tree=content_address(root, MEASURED_TARGETS),
        env=env_key(env_manifest()),
        spec=' '.join(('verify', *pytest_args)),
        log=log,
    )


def main(argv: list[str] | None = None) -> int:
    """``python -m lab_commons.dev.verify [-- pytest args]``. Returns the process exit code.

    Output goes through :func:`lab_commons.log.emit` rather than ``print``: this family never
    waives ruff's T201, and ``emit`` is the shared one-line idiom that exists for exactly this --
    a CLI tool whose stdout IS the product. No module in ``lab_commons`` calls ``print``, and this
    one does not become the first.

    A :class:`~lab_commons.dev.reports.MalformedAllowance` is turned into a one-line refusal here
    rather than allowed to reach the terminal as a traceback: the reader of that message is the
    person who typed the declaration, and a stack trace tells them about this module instead. It
    exits INCONCLUSIVE, because nothing was measured.

    :class:`~lab_commons.resources.Exhausted` takes the same route, for the same reason and with the
    same exit code: another run holds this box, nothing was measured, and INCONCLUSIVE is what a run
    that cannot say is required to say. The line NAMES the holder and the remedy, because "busy"
    sends its reader to the process table to guess and guessing wrong kills somebody's evidence.
    """
    parser = argparse.ArgumentParser(
        prog='python -m lab_commons.dev.verify',
        description='Run ruff check, ruff format --check and pytest, and print a citable verdict.',
        epilog='Exit codes: 0 pass, 1 fail (the failures are named), 2 inconclusive (the run cannot say).',
    )
    parser.add_argument(
        '--lock-wait-s',
        type=float,
        default=WAIT_S,
        metavar='SECONDS',
        help=f'ceiling on the wait for this box (default {WAIT_S:.0f}s); 0 checks once and refuses',
    )
    parser.add_argument('pytest_args', nargs='*', help='extra arguments forwarded to pytest, after a bare --')
    parsed = parser.parse_args(argv)
    try:
        verdict = run_verify(project_root(), tuple(parsed.pytest_args), wait_s=parsed.lock_wait_s)
    except MalformedAllowance as exc:
        emit(f'verify refuses to run: {exc}', err=True)
        return EXIT_CODES[Outcome.INCONCLUSIVE]
    except Exhausted as exc:
        emit(
            f'verify: inconclusive -- this box is held and nothing was measured. Held by: '
            f'{holders_line(exc)}. Wait for it, or stop that holder, then re-run; '
            f'--lock-wait-s raises or drops the {parsed.lock_wait_s:.0f}s ceiling on the wait.',
            err=True,
        )
        return EXIT_CODES[Outcome.INCONCLUSIVE]
    verdict.stamp()
    emit('')
    emit(verdict.line())
    emit(f'verify: {verdict.result.render()}')
    for failure in verdict.result.failures:
        emit(f'  failed: {failure}')
    return EXIT_CODES[verdict.result.outcome]


if __name__ == '__main__':
    raise SystemExit(main())
