"""THE VERIFY STEPS, run under one root into one log and folded into one verdict.

:func:`run_verify` runs ruff check, ruff format --check and pytest (in the box, :mod:`dev_lab.dev.verifybox`),
each streamed through :func:`_tee` into a fresh log, and :func:`build_verdict` folds their reports. The command
around it -- the run cache, the box-wide single run, the producer's post -- is :mod:`dev_lab.dev.verify`.

EVERY STEP RUNS, EVEN AFTER ONE FAILS, and that is a polarity decision rather than a convenience.
``make verify`` chains ``lint fmt-check test`` and stops at the first red, so a lint error leaves
the suite UNRUN -- and a caller reading that as "verify failed" has merged "the tests are red" with
"nobody knows whether the tests are red". Here an unrun step would be SILENT in the proof and would
drag the verdict to INCONCLUSIVE, so all three run and the verdict names the ones that failed.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Final

import lab_commons.launch as _door
from lab_commons.box import POLL_S
from lab_commons.envkey import env_key, env_manifest
from lab_commons.log import emit

from dev_lab.dev import durations
from dev_lab.dev._logdistil import distil_log
from dev_lab.dev.content import content_address
from dev_lab.dev.envseat import EnvironmentSeat
from dev_lab.dev.hook_install import read_hooks
from dev_lab.dev.logref import LogRef
from dev_lab.dev.pytestout import strip_ansi
from dev_lab.dev.reports import (
    StepReport,
    declared_skips,
    read_ruff,
    read_stages,
    stale_declarations,
    vanished_shortfall,
)
from dev_lab.dev.selection import census_scope
from dev_lab.dev.serialpass import PLUGIN, SEEN_ENV, SERIAL_BANNER, STAGE_ENV
from dev_lab.dev.test_outcomes import OUTCOMES_DIR_VAR, outcomes_dir
from dev_lab.dev.verdict import Proof, Result, Selector, Verdict
from dev_lab.dev.verifybox import (
    WAIT_S,
    boxed,
    ended_in_the_box,
    learn_ended,
    serial_width,
)

__all__ = [
    'LEDGER_PLUGIN',
    'LOG_DIRECTORY',
    'MEASURED_TARGETS',
    'OUTCOME_PLUGIN',
    'PYTEST_ARGS',
    'RUFF_STEPS',
    'build_verdict',
    'run_verify',
]

#: What the tree address covers, for EVERY repo in the family. A fixed tuple rather than a
#: per-repo list: :func:`~dev_lab.dev.content.content_address` records a target that is not
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
#: :mod:`dev_lab.dev.reports` compares names against names. A caller's own ``-r`` adds to the
#: report set rather than replacing it, so forwarding one cannot silence any of them.
#:
#:   ``s``  skips, for the two-sided skip ratchet, which cannot be checked against a number.
#:   ``f``  FAILURES. **Added 2026-09-16, and its absence was a real defect rather than a missing
#:          nicety.** With ``-rs`` alone pytest prints no ``FAILED`` line at all, so
#:          :func:`~dev_lab.dev.reports.read_pytest` saw a summary claiming N failures beside
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
#: or full, whichever conftest the selected tests sit under (:func:`dev_lab.dev.durations.pytest_configure`).
LEDGER_PLUGIN: Final[tuple[str, ...]] = ('-p', durations.__name__)

#: The per-test OUTCOME recorder a run's record is built from (inert without its env var).
OUTCOME_PLUGIN: Final[tuple[str, ...]] = ('-p', 'dev_lab.dev.test_outcomes')

#: The line that separates the ruff half of the log from the pytest half. The pytest parser is fed
#: what comes AFTER it and never the whole log, because ruff's own output can carry a ``FAILED``
#: line or a count, and a parser handed both halves would attribute one step's words to the other.
_PYTEST_BANNER: Final = '--- pytest ---\n'


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
    :data:`~dev_lab.dev.reports._FAILED_NODE` is anchored at ``^(?:FAILED|ERROR)`` -- so a
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
    with _door.popen(
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


def build_verdict(reports: tuple[StepReport, ...], *, tree: str, env: str, spec: str, log: LogRef) -> Verdict:
    """Fold the step reports into ONE verdict over the whole verify run.

    THE SELECTOR IS THE STEPS, and it is built from the step NAMES rather than from what they
    reported -- which is the only way ``silent`` can mean anything. A step that never launched
    contributes its name to ``selected`` and nothing to ``reported``, so it shows up BY NAME in the
    shortfall instead of quietly reducing the size of the run.

    Promotion is not decided here and cannot be: this hands the proof and the observed failures to
    :meth:`~dev_lab.dev.verdict.Result.settled`, which refuses PASS or FAIL over an incomplete
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
    poll_s: float = POLL_S,
    hooks: bool = True,
) -> Verdict:
    """Run the three steps under *root*, tee them into a fresh log, and return the verdict.

    *hooks* adds :data:`~dev_lab.dev.hook_install.HOOKS_STEP`, which guards a checkout someone COMMITS from; a
    producer's checkout (*hooks* false) commits nothing and judges a sha that already passed whatever hooks it met.

    The pytest step RUNS IN THE BOX (:mod:`dev_lab.dev.verifybox`) at its declared claim: admitted
    on the machine's one ledger within *wait_s*, held to its cores, memory and wall. The interpreter's
    ENVIRONMENT seat (:class:`~dev_lab.dev.envseat.EnvironmentSeat`) is held across all three steps, so
    no dependency door mutates the environment the run is judged in.

    The skip allowance is read BEFORE any step launches, so a declaration nobody can parse is
    refused against a tree that has not yet spent twenty minutes being tested -- and so is an entry
    whose SUBJECT has left the checkout (:func:`~dev_lab.dev.reports.stale_declarations`), which
    is the one side of the ratchet a selected invocation can still judge.

    THE SEAT IS TAKEN AFTER :func:`~dev_lab.dev.reports.declared_skips` AND NOT BEFORE: an
    unparseable declaration is refused against a tree that has not yet queued for anything.

    THE LOG IS READ BACK STREAMED AND IS NEVER RESIDENT, which is why the last two lines go through
    :mod:`dev_lab.dev._logdistil` rather than ``path.read_text()``. MEASURED 2026-09-18: a
    400,000-line / 80.8 MB run completes at ``rc=0``, and reading that whole log back to parse it
    costs a multiple of it in memory -- a runaway run was a ``MemoryError`` and NO verdict, in the
    module whose entire job is to leave one. That module's docstring carries the choice and what was
    rejected; here it is enough that ``distil_log`` holds one line at a time and that
    ``Distillate.annotate`` is the only thing in this function that can add a reason to the report.

    Raises:
        MalformedAllowance: ``[tool.dev_lab.verify] allowed_skips`` is present and unreadable.
        Refused: the box had no room for the selection within *wait_s*. Nothing was measured either
            way, so there is no verdict to return; :func:`dev_lab.dev.verify.main` renders both as INCONCLUSIVE.
        UnverifiableLog: the log came out empty or unreadable, so no verdict may rest on it.
            :class:`~dev_lab.dev.logref.LogRef` refuses an empty log, and this refuses with it
            rather than stamping a verdict whose evidence says nothing; :func:`dev_lab.dev.verify.main` renders it as
            INCONCLUSIVE. It was a ``SystemExit(<str>)`` until 2026-10-11, which Python exits as 1 --
            a FAIL nobody measured.

    """
    allowed = declared_skips(root)
    vanished = vanished_shortfall(stale_declarations(root, allowed))
    directory = root / LOG_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'verify-{datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")}.log'
    reports: list[StepReport] = []
    seat = EnvironmentSeat(sys.prefix, f'verify:{root.name}', wait_s=wait_s, poll_s=poll_s)
    with seat.held(), path.open('w', encoding='utf-8') as handle:
        if hooks:
            reports.append(read_hooks(root, handle=handle))
        for name, arguments in RUFF_STEPS:
            reports.append(read_ruff(name, _tee([sys.executable, '-m', *arguments], cwd=root, handle=handle)))
        handle.write(_PYTEST_BANNER)
        stamp = {
            durations.LEDGER_TREE_VAR: content_address(root, MEASURED_TARGETS),
            durations.LEDGER_ENV_VAR: env_key(env_manifest()),
            OUTCOMES_DIR_VAR: str(outcomes_dir(path)),
        }
        pytest = [sys.executable, '-m', 'pytest', *PYTEST_ARGS, *LEDGER_PLUGIN, *OUTCOME_PLUGIN, *PLUGIN, *pytest_args]
        seen = path.with_suffix('.serial-seen')
        argv, record = boxed(root, pytest, queue_s=wait_s, outcome=path.with_suffix('.outcome.json'))
        codes = [_tee(argv, cwd=root, handle=handle, extra_env={**stamp, STAGE_ENV: 'parallel', SEEN_ENV: str(seen)})]
        learn_ended(root, pytest, record)
        cut = ended_in_the_box(record)
        if seen.exists():  # the parallel stage deselected a `serial` test: it runs now, alone
            handle.write(SERIAL_BANNER)
            argv, record = boxed(root, [*pytest, *serial_width()], queue_s=wait_s, outcome=seen.with_suffix('.json'))
            codes.append(_tee(argv, cwd=root, handle=handle, extra_env={**stamp, STAGE_ENV: 'serial'}))
            cut += ended_in_the_box(record)
    stages = [distil_log(path, banner=_PYTEST_BANNER, until=SERIAL_BANNER)]
    stages += [distil_log(path, banner=SERIAL_BANNER) for _ in codes[1:]]
    complete_census, scope_refusal = census_scope(pytest_args)
    report = read_stages(
        tuple((one.text, code) for one, code in zip(stages, codes, strict=True)),
        allowed_skips=allowed,
        complete_skip_census=complete_census,
    )
    report = replace(report, truncated=(*report.truncated, *scope_refusal, *vanished, *cut))
    reports.append(functools.reduce(lambda done, stage: stage.annotate(done), stages, report))
    return build_verdict(
        tuple(reports),
        tree=content_address(root, MEASURED_TARGETS),
        env=env_key(env_manifest()),
        spec=' '.join(('verify', *pytest_args)),
        log=LogRef.of(path),
    )
