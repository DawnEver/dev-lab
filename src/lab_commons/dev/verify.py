"""The family's ONE verify entry point: ``python -m lab_commons.dev.verify``.

WHY IT IS HERE AND NOT IN A REPO. Four repos share this library, and exactly one of them --
consumer-a -- has an entry point that produces a :class:`~lab_commons.dev.verdict.Verdict`
(a 1770-line ``scripts/gate/runner.py`` that knows about cases, solvers and vendor engines, and
is not portable to a repo that has none of those). The other three have NOTHING, so an agent
working in one can only type a bare ``pytest`` line -- which the family's hooks deny, and they
deny it for the reason this module exists: a bare invocation returns an exit code, and an exit
code cannot say whether the run COVERED what it selected. This module is the portable remainder:
three steps, a log, and a verdict built out of the algebra in :mod:`lab_commons.dev.verdict` --
plus :data:`HOOKS_STEP`, which fails the run when a hook the repo declares is not installed.

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
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final

from lab_commons.dev import durations
from lab_commons.dev._logdistil import distil_log
from lab_commons.dev.boxwait import WAIT_S, hold_the_box, holders_line
from lab_commons.dev.content import content_address
from lab_commons.dev.envkey import env_key, env_manifest
from lab_commons.dev.forgestatus import GATE_CONTEXT, head_sha, publish, verdict_commit
from lab_commons.dev.hook_install import UNPROTECTED, hook_installation, install_command
from lab_commons.dev.inflight import RunKey, box_directory, run_once
from lab_commons.dev.logref import LogRef, UnverifiableLog
from lab_commons.dev.pytestout import strip_ansi
from lab_commons.dev.reports import (
    MalformedAllowance,
    StepReport,
    declared_skips,
    read_pytest,
    read_ruff,
    stale_declarations,
)
from lab_commons.dev.treedirt import status_paths
from lab_commons.dev.verdict import Outcome, Proof, Result, Selector, Verdict
from lab_commons.dev.verdictledger import (
    OUTCOMES_DIR_VAR,
    ledger_path,
    outcomes_dir,
    record_promoted,
    run_test_id,
    served,
)
from lab_commons.log import emit
from lab_commons.resources import DEFAULT_POLL_S, Exhausted

__all__ = [
    'EXIT_CODES',
    'HOOKS_STEP',
    'LOG_DIRECTORY',
    'MEASURED_TARGETS',
    'OUTCOME_PLUGIN',
    'PYTEST_ARGS',
    'RUFF_STEPS',
    'build_verdict',
    'main',
    'project_root',
    'read_hooks',
    'run_key',
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
#:          committed by the module that forbids it. MEASURED on consumer-c: `2 failed, 130 passed`
#:          read as `inconclusive ... the summary names 2 failure(s) and the output names 0 node
#:          id(s)`.
#:   ``E``  ERRORS, for the same reason one letter over: an errored test is not a failed one, and a
#:          count of errors with no names attached is a shortfall nobody can act on.
#:
#: The disagreement check that caught this is kept exactly as it is. It was right -- the summary and
#: the named set genuinely disagreed -- and it is what turned a silent mis-classification into a
#: loud refusal. The bug was never the check; it was asking pytest for less than the check needs.
#:
#: AND ``--no-fold-skipped``, FOR THE SAME REASON ONE STEP FURTHER. Measured 2026-10-07 against the
#: installed pytest: ``-rs`` FOLDS the skip summary into ``SKIPPED [2] tests/test_vendor.py:31:
#: reason`` -- grouped by (file, line, reason), with no node id in the line and a LINE NUMBER in its
#: place. Every allowance in every consumer was therefore keyed on a fact about a file's layout, and
#: a consumer measured what that costs: a five-line comment moved a skip from ``:101`` to ``:106`` and
#: an entry that had just been re-measured by hand stopped matching, so every verdict from that
#: checkout read INCONCLUSIVE. ``--no-fold-skipped`` selects pytest's other skip summary --
#: ``SKIPPED <node id> - <reason>``, one line per skip -- and a node id is the name of the test.
PYTEST_ARGS: Final[tuple[str, ...]] = ('-rfEs', '--no-fold-skipped')

#: The durations ledger, loaded as a plugin so EVERY verify run records what it executed -- targeted
#: or full, whichever conftest the selected tests sit under (:func:`lab_commons.dev.durations.pytest_configure`).
LEDGER_PLUGIN: Final[tuple[str, ...]] = ('-p', durations.__name__)

#: The per-test OUTCOME recorder the verdict ledger is filled from (inert without its env var).
OUTCOME_PLUGIN: Final[tuple[str, ...]] = ('-p', 'lab_commons.dev.verdictledger')

#: The process exit code each outcome maps to. FAIL and INCONCLUSIVE are distinct because their
#: remedies are distinct: one is "fix the code", the other is "nobody knows yet".
EXIT_CODES: Final[dict[Outcome, int]] = {Outcome.PASS: 0, Outcome.FAIL: 1, Outcome.INCONCLUSIVE: 2}

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


def _tee(command: list[str], *, cwd: Path, handle: IO[str], extra_env: dict[str, str] | None = None) -> int:
    r"""Run *command*, streaming its merged output to *handle* AND to this process's stdout.

    STREAMED rather than captured and written afterwards, so a step that hangs still leaves in the
    log what it had printed when somebody killed it -- and so a step that is merely SLOW shows
    progress while it runs, which is the property this function is measured against.

    MEASURED 2026-09-16, on consumer-b: a run sat 26+ minutes with nothing in its log but the two ruff
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
    bar into lines -- ugly in a log, never fatal to a parse -- and the CSI grammar cannot match it.
    """
    handle.write(f'$ {" ".join(command)}\n')
    handle.flush()
    env = os.environ | {'PYTHONUNBUFFERED': '1', 'PYTHONIOENCODING': 'utf-8'} | (extra_env or {})
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
            line = strip_ansi(raw)
            handle.write(line)
            handle.flush()
            emit(line.rstrip('\n'), flush=True)
    return process.returncode


#: The step name the hooks-installed check reports under (user directive 2026-09-23). A STEP rather
#: than a test so that a verify narrowed to one path still runs it: the adoption test only runs when
#: a suite selects it, and the only path that skips this is one where verify is not run at all.
HOOKS_STEP: Final = 'hooks-installed'


def read_hooks(root: Path, *, handle: IO[str]) -> StepReport:
    """The hooks-installed step: a named failure when a declared hook is not live, with its remedy.

    It reads and never installs -- the install act is :func:`lab_commons.dev.hook_install.install`,
    called from each repo's bootstrap. ``nothing-declared`` passes: a repo with no configuration has
    no hook for this step to find missing.
    """
    report = hook_installation(root)
    handle.write(f'$ {HOOKS_STEP}: {report.verdict} ({report.hooks_dir})\n')
    for stage in report.failing:
        handle.write(f'  {stage.stage:<12} {stage.status:<28} {stage.detail}\n')
    if report.verdict == UNPROTECTED:
        handle.write(f'  remedy: python {" ".join(install_command(root))}\n')
    handle.flush()
    failed = (HOOKS_STEP,) if report.verdict == UNPROTECTED else ()
    return StepReport(name=HOOKS_STEP, reported=(HOOKS_STEP,), failures=failed)


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


def _vanished_shortfall(stale: tuple[str, ...]) -> tuple[str, ...]:
    """The refusal for a declaration whose SUBJECT left the checkout, read off the tree.

    Its own function because it is the one shortfall no step produced: every other reason in
    :func:`run_verify` is read out of what a process PRINTED, and this one is read out of the files a
    declaration names -- so it binds before anything launches, and on a selected invocation too,
    where the run cannot judge anybody else's allowance retired.
    """
    if not stale:
        return ()
    reason = (
        f'declared in [tool.lab_commons.verify] allowed_skips and naming nothing in this checkout: '
        f'{", ".join(stale)}. An entry is read as a pytest NODE ID -- a module path, optionally '
        f'followed by ::test_name -- so one that resolves to no file names no test at all. Delete it '
        f'in the same edit that removed its subject, or point it at the name that replaced it.'
    )
    return (reason,)


def _skip_census_scope(arguments: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    """Only known presentation flags preserve a full-suite skip census.

    This is not a pytest parser: it recognises selection and the few display-only flags whose
    semantics establish this proof. Unknown options refuse a census claim instead of silently
    disabling the reverse ratchet. The original arguments still name the verdict's selector.
    """
    complete = True
    unknown: list[str] = []
    arguments_left = iter(arguments)
    for argument in arguments_left:
        if argument in ('-k', '-m', '--deselect'):
            complete = False
            if next(arguments_left, None) is None:
                unknown.append(argument)
        elif argument.startswith(('--deselect=', '-k=', '-m=')) or not argument.startswith('-'):
            complete = False
        elif argument in ('--verbose', '--quiet', '-s') or (
            argument.startswith('-') and len(argument) > 1 and set(argument[1:]) <= {'v', 'q'}
        ):
            continue
        else:
            unknown.append(argument)
    reasons = (
        (
            (
                f'cannot establish skip census scope for pytest option(s) {", ".join(unknown)}; '
                'use a supported selector or a full-suite invocation'
            ),
        )
        if unknown
        else ()
    )
    return complete and not unknown, reasons


def run_verify(
    root: Path,
    pytest_args: tuple[str, ...] = (),
    *,
    wait_s: float = WAIT_S,
    poll_s: float = DEFAULT_POLL_S,
) -> Verdict:
    """Run the three steps under *root*, tee them into a fresh log, and return the verdict.

    The skip allowance is read BEFORE any step launches, so a declaration nobody can parse is
    refused against a tree that has not yet spent twenty minutes being tested -- and so is an entry
    whose SUBJECT has left the checkout (:func:`~lab_commons.dev.reports.stale_declarations`), which
    is the one side of the ratchet a selected invocation can still judge.

    THE BOX IS HELD ACROSS ALL THREE STEPS and not only pytest, because the measured harm was 194
    CPU-minutes of a process TREE and ruff over a large tree is not free either.

    IT IS TAKEN AFTER :func:`~lab_commons.dev.reports.declared_skips` AND NOT BEFORE, which is the
    one place this departs from the plan it implements. That call is documented to run before any
    step launches so an unparseable declaration is refused against a tree that has not yet spent
    twenty minutes being tested; acquiring first would make the same refusal arrive up to thirty
    minutes later, having queued for a box it was never going to use.

    THE LOG IS READ BACK STREAMED AND IS NEVER RESIDENT, which is why the last two lines go through
    :mod:`lab_commons.dev._logdistil` rather than ``path.read_text()``. MEASURED 2026-09-18: a
    400,000-line / 80.8 MB run completes at ``rc=0``, and reading that whole log back to parse it
    costs a multiple of it in memory -- a runaway run was a ``MemoryError`` and NO verdict, in the
    module whose entire job is to leave one. That module's docstring carries the choice and what was
    rejected; here it is enough that ``distil_log`` holds one line at a time and that
    ``Distillate.annotate`` is the only thing in this function that can add a reason to the report.

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
    vanished = _vanished_shortfall(stale_declarations(root, allowed))
    directory = root / LOG_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'verify-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}.log'
    reports: list[StepReport] = []
    with contextlib.ExitStack() as box, path.open('w', encoding='utf-8') as handle:
        hold_the_box(box, f'verify:{root.name}', wait_s=wait_s, poll_s=poll_s)
        reports.append(read_hooks(root, handle=handle))
        for name, arguments in RUFF_STEPS:
            reports.append(read_ruff(name, _tee([sys.executable, '-m', *arguments], cwd=root, handle=handle)))
        handle.write(_PYTEST_BANNER)
        stamp = {
            durations.LEDGER_TREE_VAR: content_address(root, MEASURED_TARGETS),
            durations.LEDGER_ENV_VAR: env_key(env_manifest()),
            OUTCOMES_DIR_VAR: str(outcomes_dir(path)),
        }
        command = [sys.executable, '-m', 'pytest', *PYTEST_ARGS, *LEDGER_PLUGIN, *OUTCOME_PLUGIN, *pytest_args]
        code = _tee(command, cwd=root, handle=handle, extra_env=stamp)
    distillate = distil_log(path, banner=_PYTEST_BANNER)
    complete_census, scope_refusal = _skip_census_scope(pytest_args)
    report = read_pytest(distillate.text, returncode=code, allowed_skips=allowed, complete_skip_census=complete_census)
    reports.append(
        distillate.annotate(
            StepReport(
                name=report.name,
                reported=report.reported,
                failures=report.failures,
                truncated=(*report.truncated, *scope_refusal, *vanished),
            )
        )
    )
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

    EVERY RUN IS THEN PUBLISHED as the ``lab/gate`` commit status (VERDICT-AS-STATUS, see
    :mod:`lab_commons.dev.forgestatus`) -- on HEAD only when the tree was clean before and after the
    run and HEAD did not move; INCONCLUSIVE posts ``error`` naming itself. ``--no-status`` opts out. The publish
    prints one line and can neither raise nor change the exit code: the verdict is the run's.
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
    parser.add_argument('--no-status', action='store_true', help='do not post the verdict as a lab/gate status')
    parser.add_argument('--rerun', action='store_true', help='run even when the ledger already judged this key')
    parser.add_argument('pytest_args', nargs='*', help='extra arguments forwarded to pytest, after a bare --')
    parsed = parser.parse_args(argv)
    root = project_root()
    arguments = tuple(parsed.pytest_args)
    key = run_key(root, arguments)
    ledger = ledger_path(root)
    cited = None if parsed.rerun else served(ledger, tree=key.tree, env=key.env, test=run_test_id(key.selector))
    if cited is not None:
        emit(
            f'verify: CITED {cited.result} -- the ledger ({ledger}) already judged this tree, env and selection; '
            f'evidence: {cited.log}. Nothing ran; --rerun runs it again.'
        )
        return EXIT_CODES[Outcome(cited.result.lower())]

    def lead() -> str:
        code, lines = _judge(root, arguments, key, ledger, wait_s=parsed.lock_wait_s, no_status=parsed.no_status)
        return json.dumps({'code': code, 'lines': lines})

    answer, attached = run_once(key, lead, directory=box_directory(), poll_s=DEFAULT_POLL_S)
    shared = json.loads(answer)
    if attached:
        emit('verify: ATTACHED to the run already in flight for this tree, env and selection; its answer:')
        for line in shared['lines']:
            emit(line)
    return int(shared['code'])


def run_key(root: Path, pytest_args: tuple[str, ...]) -> RunKey:
    """What makes two verify requests ONE run: the tree address, the env key and the selection."""
    return RunKey(
        tree=content_address(root, MEASURED_TARGETS),
        env=env_key(env_manifest()),
        selector=' '.join(('verify', *pytest_args)),
    )


def _judge(
    root: Path, arguments: tuple[str, ...], key: RunKey, ledger: Path, *, wait_s: float, no_status: bool
) -> tuple[int, list[str]]:
    """The leader's run: judge, stamp, record, publish, and return the exit code with the lines it printed."""
    head, start = head_sha(root), status_paths(root)
    try:
        verdict = run_verify(root, arguments, wait_s=wait_s)
    except MalformedAllowance as exc:
        line = f'verify refuses to run: {exc}'
        emit(line, err=True)
        return EXIT_CODES[Outcome.INCONCLUSIVE], [line]
    except Exhausted as exc:
        line = (
            f'verify: inconclusive -- this box is held and nothing was measured. Held by: '
            f'{holders_line(exc)}. Wait for it, or stop that holder, then re-run; '
            f'--lock-wait-s raises or drops the {wait_s:.0f}s ceiling on the wait.'
        )
        emit(line, err=True)
        return EXIT_CODES[Outcome.INCONCLUSIVE], [line]
    verdict.stamp()
    lines = [verdict.line(), f'verify: {verdict.result.render()}']
    lines += [f'  failed: {failure}' for failure in verdict.result.failures]
    emit('')
    for line in lines:
        emit(line)
    commit = verdict_commit(head, head_sha(root), start, status_paths(root))
    if run_key(root, ()).tree == key.tree:
        record_promoted(ledger, verdict, key.tree, key.env, key.selector, commit=commit or '')
    if not no_status:
        emit(publish(root, verdict, context=GATE_CONTEXT, commit=commit))
    return EXIT_CODES[verdict.result.outcome], lines


if __name__ == '__main__':
    raise SystemExit(main())
