"""NETWORK-RETRY-THEN-REPORT: a bounded retry around a network verb, and a REPORT the caller reads.

THE FAMILY VACUUM THIS CLOSES, MEASURED 2026-09-17. The rule has been in the shared registry since
it was written, and its only mechanism anywhere is ``motronics-studio/scripts/hooks/with-retry.sh``
-- which stamps a ``MOTRONICS_PUSH_ID`` and hands it to that repo's ``push_lock.py``, so it is that
repo's gate machinery rather than a family capability and was never portable. ``wdg-lab`` has the
SUBJECT and no mechanism at all: ``scripts/pull_all.py`` calls ``git clone``/``git pull`` with a
timeout and ZERO retries, and ``scripts/wdg-lab-update.sh`` exits on the first failed ``fetch`` --
so a five-minute timer turns one DNS blip into ``FETCH FAILED`` and a skipped deploy. That repo had
to leave the rule ABSENT with the reason "a guard would demand a file that cannot exist". This is
the file.

WHAT IS UNIVERSAL AND WHAT WAS LOCAL, read off the shell wrapper rather than guessed:

* UNIVERSAL -- a bounded attempt count with a backoff between attempts; the whole combined output
  being what the classification reads; the PERMANENT/TRANSIENT split and the refusal to spend the
  remaining attempts on a permanent; capturing the exit code immediately; and reporting with a
  diagnosis instead of the word "blocked".
* LOCAL -- ``MOTRONICS_PUSH_ID``, ``push_lock.py``, the interpreter search that finds a worktree's
  shared ``.venv``, and "is this push blocked by MY OWN previous attempt's gate". That last one is
  genuinely universal in SHAPE and has no portable answer: it needs a repo's own lock. It is reached
  here through *before_retry*, so an adopter supplies the answer without forking the loop.

A REPORT, NOT A PRINTED STRING. "Reports with its diagnosis" is the half that makes this rule worth
having, and a sentence on stderr is not something a caller can branch on. :class:`Report` is DATA:
every attempt with its own diagnosis, a :class:`Disposition` that says whether the loop recovered,
refused or ran out, and a remedy sentence DERIVED from those rather than stored beside them. The two
known consumers are one Python caller and one shell caller, so the report also renders as JSON
through ``python -m lab_commons.dev.netverb``.

REACHED BY NAME, NEVER COPIED -- the :mod:`lab_commons.dev.githooks` shape rather than the
:mod:`lab_commons.dev.agenthooks` one. ``agenthooks`` installs a stamped copy because a
``PreToolUse`` command line lives in a committed ``settings.json`` read on other boxes and runs on
every tool call. Neither pressure exists here: a shell caller already has an interpreter (both known
consumers run inside a ``.venv``) and a fetch costs a network round trip, so one interpreter start
is noise. A copied payload would be the fork this family refuses, and a stamp is only worth paying
for when nothing else can be done.

IT COMPOSES WITH :mod:`lab_commons.dev.bounded` RATHER THAN RESTATING IT. Every attempt runs through
:func:`~lab_commons.dev.bounded.run_bounded`, so the wall terminates the process TREE -- which is
the defect that module exists for and is not re-decided here. This module owns exactly the
remainder: how many attempts, which failures deserve one, and what the caller is told.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from lab_commons.dev._netverb_rows import ROWS
from lab_commons.dev.bounded import run_bounded
from lab_commons.log import emit

__all__ = [
    'DEFAULT_ATTEMPTS',
    'DEFAULT_BACKOFF_S',
    'Attempt',
    'Diagnosis',
    'Disposition',
    'Report',
    'classify',
    'is_retryable',
    'main',
    'run_network_verb',
]

#: Three, and it is the number every repo in this family already states in prose. A ceiling on the
#: WAIT rather than a target: the loop stops early on a permanent and reports.
DEFAULT_ATTEMPTS: Final = 3

#: Seconds between attempts. Small, because the thing being waited out is a credential refresh or a
#: DNS answer, not a server's maintenance window -- and a long backoff inside a five-minute deploy
#: timer is a second way to miss the deploy.
DEFAULT_BACKOFF_S: Final = 3.0


class Diagnosis(StrEnum):
    """WHY an attempt ended the way it did -- the thing a caller branches on.

    ``UNCLASSIFIED`` is the deliberate default and is RETRYABLE, which is the asymmetry this whole
    module rests on: a shape nobody has measured may be transient, and the cost of retrying a
    permanent is bounded by the attempt count, while the cost of NOT retrying a transient is a false
    "blocked" report -- the exact incident (2026-08-21) the rule was written for.
    """

    SUCCEEDED = 'succeeded'
    TRANSIENT = 'transient'
    TIMED_OUT = 'timed-out'
    UNCLASSIFIED = 'unclassified'
    HOOK_REFUSED = 'hook-refused'
    REF_REJECTED = 'ref-rejected'
    FORGE_REFUSED = 'forge-refused'
    REMOTE_ABSENT = 'remote-absent'
    STOPPED_BY_CALLER = 'stopped-by-caller'


class Disposition(StrEnum):
    """What the LOOP did, which is a different question from why one attempt failed.

    ``RECOVERED`` exists so the caller can tell a clean first-try success from a flaky network the
    wrapper absorbed: reporting both as ``SUCCEEDED`` would hide precisely the evidence that says
    whether this rule is still earning its keep.
    """

    SUCCEEDED = 'succeeded'
    RECOVERED = 'recovered'
    REFUSED = 'refused'
    EXHAUSTED = 'exhausted'


#: The diagnoses an attempt may be repeated on. Derived from the table's own ``retryable`` column so
#: the data half stays the one place a row's disposition is decided, plus the two diagnoses the
#: machinery itself produces: a wall (the box was busy; the next attempt may fit) and the unmeasured
#: default.
_RETRYABLE: Final[frozenset[str]] = frozenset(name for name, retryable, _ in ROWS if retryable) | {
    Diagnosis.TIMED_OUT.value,
    Diagnosis.UNCLASSIFIED.value,
}


def is_retryable(diagnosis: Diagnosis) -> bool:
    """Whether another attempt could plausibly answer differently -- the table's decision, read."""
    return diagnosis.value in _RETRYABLE


def classify(output: str) -> Diagnosis:
    """The FIRST row in the table whose pattern is present, else ``UNCLASSIFIED``.

    Pure over its argument, so the tests drive this function itself rather than a second
    implementation that would agree with it by construction. Case-insensitive substring matching
    over the WHOLE combined output: a hook writes its refusal to stdout while git writes its own
    failure to stderr, and a reader of one is blind to the other.
    """
    haystack = output.lower()
    for name, _retryable, patterns in ROWS:
        if any(pattern in haystack for pattern in patterns):
            return Diagnosis(name)
    return Diagnosis.UNCLASSIFIED


@dataclass(frozen=True, slots=True)
class Attempt:
    """One invocation: what it returned, what it said, and what that says about trying again."""

    index: int
    returncode: int
    output: str
    diagnosis: Diagnosis

    @property
    def ok(self) -> bool:
        """Whether this single attempt exited clean."""
        return self.returncode == 0

    @property
    def retryable(self) -> bool:
        """Whether this attempt's diagnosis is one a retry could clear."""
        return is_retryable(self.diagnosis)

    def as_dict(self) -> dict[str, object]:
        """The attempt as JSON-ready data, diagnosis included -- the shell caller reads this too."""
        return {
            'index': self.index,
            'returncode': self.returncode,
            'diagnosis': self.diagnosis.value,
            'retryable': self.retryable,
            'output': self.output,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """THE REPORT -- what the caller branches on, with the remedy DERIVED rather than stored.

    ``attempts`` is the evidence and everything else is read off it. A caller that only wants the
    exit code has :attr:`returncode`; one that wants to tell "the network was flaky" from "the forge
    refused you" from "your hook refused you" has :attr:`diagnosis`; one reporting to a human has
    :attr:`remedy`.
    """

    argv: tuple[str, ...]
    attempts: tuple[Attempt, ...]
    allowed_attempts: int

    @property
    def ok(self) -> bool:
        """Whether the LAST attempt exited clean -- a recovered run is still ok."""
        return bool(self.attempts) and self.attempts[-1].ok

    @property
    def attempt_count(self) -> int:
        """How many attempts were actually made, which is the evidence for RECOVERED."""
        return len(self.attempts)

    @property
    def returncode(self) -> int:
        """The exit code a shell caller sees: the last attempt's, or 0 when none ran."""
        return self.attempts[-1].returncode if self.attempts else 0

    @property
    def diagnosis(self) -> Diagnosis:
        """The last attempt's diagnosis -- what the run FINALLY hit, not what it survived."""
        return self.attempts[-1].diagnosis if self.attempts else Diagnosis.SUCCEEDED

    @property
    def disposition(self) -> Disposition:
        """SUCCEEDED / RECOVERED / REFUSED / EXHAUSTED, in the only order that keeps them distinct."""
        if self.ok:
            return Disposition.SUCCEEDED if self.attempt_count == 1 else Disposition.RECOVERED
        if not is_retryable(self.diagnosis):
            return Disposition.REFUSED
        return Disposition.EXHAUSTED

    @property
    def remedy(self) -> str:
        """One sentence naming what happened AND what to do -- never the bare word "blocked"."""
        verb = ' '.join(self.argv)
        if self.disposition is Disposition.SUCCEEDED:
            return f'{verb}: succeeded on the first attempt'
        if self.disposition is Disposition.RECOVERED:
            return (
                f'{verb}: RECOVERED on attempt {self.attempt_count} of {self.allowed_attempts} -- '
                f'the earlier failures were transient and no action is needed'
            )
        if self.disposition is Disposition.REFUSED:
            return (
                f'{verb}: REFUSED on attempt {self.attempt_count} with diagnosis '
                f'{self.diagnosis.value} -- retrying cannot change this answer; read the output and '
                f'fix what was refused'
            )
        return (
            f'{verb}: gave up after {self.attempt_count} of {self.allowed_attempts} attempts, last '
            f'diagnosis {self.diagnosis.value} -- the failure looks transient and did not clear, so '
            f'report it with this output rather than repeating it'
        )

    def as_dict(self) -> dict[str, object]:
        """The JSON shape a shell caller reads: every derived property, so neither half computes."""
        return {
            'argv': list(self.argv),
            'ok': self.ok,
            'returncode': self.returncode,
            'disposition': self.disposition.value,
            'diagnosis': self.diagnosis.value,
            'attempt_count': self.attempt_count,
            'allowed_attempts': self.allowed_attempts,
            'remedy': self.remedy,
            'attempts': [attempt.as_dict() for attempt in self.attempts],
        }


def _child_env(env: Mapping[str, str] | None, *, no_prompt: bool) -> dict[str, str]:
    """The environment the verb runs in, with the interactive prompt closed off by default.

    A CREDENTIAL PROMPT IS A HANG, not a failure, and a hang defeats the whole module: the wall
    fires, the attempt is diagnosed ``TIMED_OUT``, and the next attempt prompts again. ``wdg-lab``'s
    ``pull_all.py`` already sets this by hand with the comment "a hung prompt blocks the
    auto-puller"; hoisting it here is why that caller can delete the line rather than keep it.
    """
    base = dict(os.environ if env is None else env)
    if no_prompt:
        base.setdefault('GIT_TERMINAL_PROMPT', '0')
    return base


def run_network_verb(
    argv: Sequence[str],
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff_s: float = DEFAULT_BACKOFF_S,
    timeout: float | None = None,
    cwd: Path | str | None = None,
    env: Mapping[str, str] | None = None,
    no_prompt: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    before_retry: Callable[[Attempt], bool] | None = None,
) -> Report:
    """Run *argv* until it succeeds, is refused, or runs out of attempts -- and REPORT either way.

    Never raises on a failing command: a failure IS the report. The only exceptions that escape say
    the command could not be run at all (``OSError``), which is not a network answer and must not be
    dressed as one.

    Args:
        argv: the command to run, already split -- the verb and its arguments.
        attempts: the CEILING on tries, not a target; one success ends the loop.
        backoff_s: the first backoff, doubled per retry.
        timeout: seconds allowed per ATTEMPT, or ``None`` for no bound.
        cwd: the directory the command runs in.
        env: the environment it runs in, before the no-prompt keys are applied.
        no_prompt: close off the interactive credential prompt, so a missing credential is a
            REPORTED refusal rather than a hang nobody can see.
        before_retry: an adopter's own veto, consulted after a retryable failure and BEFORE the
            backoff. Returning ``False`` stops the loop with :attr:`Diagnosis.STOPPED_BY_CALLER`.
            This is the seam motronics-studio's ``push_lock.py`` fits: "my own previous attempt's
            gate still holds the box" is a real stop no shared table can recognise, because the
            evidence for it is a repo's own lock file.
        sleep: the backoff, injected so a test can drive the REAL loop at full speed. The command
            under test is always a real subprocess; only the clock is substituted.

    """
    if attempts < 1:
        msg = f'attempts must be at least 1, got {attempts}'
        raise ValueError(msg)
    argv = tuple(argv)
    child_env = _child_env(env, no_prompt=no_prompt)
    made: list[Attempt] = []
    for index in range(1, attempts + 1):
        attempt = _attempt(index, argv, cwd=cwd, env=child_env, timeout=timeout)
        made.append(attempt)
        if attempt.ok or not attempt.retryable:
            break
        if before_retry is not None and not before_retry(attempt):
            made[-1] = Attempt(attempt.index, attempt.returncode, attempt.output, Diagnosis.STOPPED_BY_CALLER)
            break
        if index < attempts:
            sleep(backoff_s)
    return Report(argv=argv, attempts=tuple(made), allowed_attempts=attempts)


def _attempt(
    index: int,
    argv: tuple[str, ...],
    *,
    cwd: Path | str | None,
    env: Mapping[str, str],
    timeout: float | None,
) -> Attempt:
    """One invocation, through the tree-killing wall. Both streams, because both carry evidence."""
    try:
        done = run_bounded(argv, cwd=cwd, env=dict(env), text=True, encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as expired:
        return Attempt(index, 124, str(expired.output or ''), Diagnosis.TIMED_OUT)
    output = (done.stdout or '') + (done.stderr or '')
    if done.returncode == 0:
        return Attempt(index, 0, output, Diagnosis.SUCCEEDED)
    return Attempt(index, done.returncode, output, classify(output))


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m lab_commons.dev.netverb [options] -- <command>`` -- the shell caller's door.

    Exits with the command's own last exit code, so a shell caller that only cares whether it worked
    keeps its ``if ! ...; then`` shape unchanged. ``--json`` prints the whole report on stdout for a
    caller that wants to branch on the diagnosis, and the command's own output always goes to stderr
    so the two never mix.
    """
    parser = argparse.ArgumentParser(prog='lab_commons.dev.netverb', description='bounded retry, then report')
    parser.add_argument('--attempts', type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument('--backoff', type=float, default=DEFAULT_BACKOFF_S)
    parser.add_argument('--timeout', type=float, default=None)
    parser.add_argument('--cwd', default=None)
    parser.add_argument('--json', action='store_true', help='print the report as JSON on stdout')
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    command = [word for word in args.command if word != '--']
    if not command:
        parser.error('no command given -- usage: python -m lab_commons.dev.netverb -- git fetch origin')
    report = run_network_verb(
        command, attempts=args.attempts, backoff_s=args.backoff, timeout=args.timeout, cwd=args.cwd
    )
    # The narrative goes to stderr and the machine-readable report to stdout, which is the split a
    # shell caller branches on; a logger here would send a CLI's own output through a sink nobody
    # asked for. Both halves go through ``emit`` rather than ``print``, which is what retired the
    # four T201 waivers that used to stand here: the attempt OUTPUT below is a SUBPROCESS's, so its
    # characters are the remote tool's choice and not ours, and a console that cannot encode one
    # must not take the report down with it.
    for attempt in report.attempts:
        head = f'[netverb] attempt {attempt.index}/{report.allowed_attempts}: {attempt.diagnosis.value}'
        emit(head, err=True)
        if attempt.output:
            emit(attempt.output.removesuffix('\n'), err=True)
    emit(f'[netverb] {report.remedy}', err=True)
    if args.json:
        emit(json.dumps(report.as_dict(), indent=2))
    return report.returncode


if __name__ == '__main__':
    raise SystemExit(main())
