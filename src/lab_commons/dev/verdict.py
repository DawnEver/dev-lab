"""The verdict algebra -- the one thing that makes a claim about a run checkable by somebody else.

    Verdict = (tree, env, selector, result, log)

THE POLARITY IS THE WHOLE DESIGN, and it is the opposite of the system this replaces. That system
treated a run as TRUSTED and demoted it when something noticed a problem, so every way of running
incompletely that nobody had thought of read as a PASS. Here a result STARTS ``INCONCLUSIVE`` and is
PROMOTED only on PROOF that the run covered what it selected. A proof that fails to arrive leaves
the result exactly where it began, so a new way of running incompletely -- one nobody has thought of
yet -- degrades to "we do not know" instead of to "it passed". That is measured, not preferred:
2026-09-15, `optimi_lab` as configured collected 307 tests, hit 3 collection errors, printed
"Interrupted" and ran ZERO of them -- and nothing in the repo told that apart from the same
invocation printing "307 passed".

THE THREE OUTCOMES ARE A TOTAL ENUM, never a bool. ``fail_under`` is the cautionary case in the
same measurement: 97.93 % coverage measured and never gating, because a number with no outcome
attached cannot refuse anything.

    PASS / FAIL  settled: the selector was covered, and the failures are NAMED
    INCONCLUSIVE not settled: the run cannot say, and it carries WHY in its own words

``Result.settled`` does not take "passed": it takes the FAILURES OBSERVED and derives the outcome,
so a caller cannot ask for a pass -- it can only fail to name one. Promotion is refused by
:class:`Proof` when anything selected went silent or unreported.

WHY (tree, env) ARE PART OF THE VERDICT AND NOT METADATA ABOUT IT. A different tree or a different
set of resolved packages means the verdict does NOT EXIST -- not that it is stale. ``tree`` is a
content address (:mod:`lab_commons.dev.content`), so a tree that moves MID-RUN changes it, which is
the limitation the ``HEAD + "-dirty"`` stamp was measured to have and the reason this is not a SHA.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from lab_commons.dev.logref import MARKER, LogRef

__all__ = ['IncompleteRun', 'Outcome', 'Proof', 'Result', 'Selector', 'Verdict']


class IncompleteRun(RuntimeError):
    """A result was promoted to PASS or FAIL by a run that did not prove it covered its selector.

    ITS OWN CLASS rather than a ``ValueError``, because the caller it is aimed at is a runner: the
    fix is to make the run report everything it selected (or to record WHICH node id stayed
    silent), and a generic refusal would send that reader looking for a bad argument instead.
    """


class Outcome(Enum):
    """The three states a run can be in. TOTAL, and INCONCLUSIVE is the starting member.

    Not a bool, and not an ``Optional[bool]``: ``None``/``False`` collapses "it ran and failed" with
    "it did not really run", and every repair that follows from that collapse edits the digit rather
    than running the suite.
    """

    INCONCLUSIVE = 'inconclusive'
    PASS = 'pass'
    FAIL = 'fail'

    @property
    def settled(self) -> bool:
        """Whether the run PROVED an answer, as opposed to being unable to say."""
        return self is not Outcome.INCONCLUSIVE


@dataclass(frozen=True, slots=True)
class Selector:
    """What the run was ASKED to cover, and what that expands to. Named, never counted.

    ``spec`` is what a human asked for (``'gate'``, ``'tests/unit/hamilton'``, a node id list) and
    ``node_ids`` is its EXPANSION, which is the thing a proof can be checked against -- a count
    cannot say WHICH node went missing, which is the lesson `.claude/rules/rem/integration.md`
    records from a pin that read "2" while the table delivered one.
    """

    spec: str
    node_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.spec.strip():
            msg = 'a selector with no spec does not say what was asked for, so no reader can re-issue it.'
            raise ValueError(msg)
        # SORTED AND DEDUPLICATED HERE, so two calls that select the same set agree byte for byte:
        # a set has no order, and an expansion that inherited one would make an identical run
        # address differently for the sole reason that pytest enumerated in another order.
        expanded = tuple(sorted(set(self.node_ids)))
        if not expanded:
            msg = (
                f'selector {self.spec!r} expands to nothing, so it cannot be part of a verdict. A '
                f'run that selected no test proved nothing, and "found nothing" must never be the '
                f'same value as "found nothing wrong".'
            )
            raise ValueError(msg)
        object.__setattr__(self, 'node_ids', expanded)


@dataclass(frozen=True, slots=True)
class Proof:
    """Evidence that a run COVERED its selector: what was asked for, and what reported.

    Three facts and no verdict: ``truncated`` names anything that cut the run short (a wall, a
    ceiling, a collection error, an interrupted worker) and is a NAMED SET rather than a flag,
    because "it hit the wall" and "collection failed" have different remedies.

    ``reported`` is the node ids that produced an OUTCOME -- pass, fail, or error. A SKIP IS NOT AN
    OUTCOME AND DOES NOT BELONG HERE: it is a selected test that told nobody anything, it lands in
    :attr:`silent`, and it makes the proof incomplete. That is the suite-side spelling of this
    repo's rule that a known failure is an ``xfail`` with its residual, never a ``skip``.
    """

    selected: tuple[str, ...]
    reported: frozenset[str]
    truncated: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        selector: Selector,
        reported: Iterable[str],
        *,
        truncated: Iterable[str] = (),
    ) -> Proof:
        """The proof a run of *selector* actually earned, from the node ids that reported."""
        return cls(
            selected=selector.node_ids,
            reported=frozenset(reported),
            truncated=tuple(sorted(set(truncated))),
        )

    @property
    def silent(self) -> tuple[str, ...]:
        """Selected node ids that never reported. Each one is a hole in the run, named."""
        seen = set(self.reported)
        return tuple(node for node in self.selected if node not in seen)

    @property
    def unexpected(self) -> tuple[str, ...]:
        """Node ids that reported without being selected. The run is not the run it declared.

        Not the harmless direction it looks like. A verdict is cited against its selector, and a
        selector that does not describe what ran cannot be re-issued by the reader -- so an
        under-approximating selector makes the verdict unreproducible even when every test passed.
        """
        selected = set(self.selected)
        return tuple(sorted(node for node in self.reported if node not in selected))

    @property
    def complete(self) -> bool:
        """Whether every selected node reported, nothing extra did, and nothing cut the run short."""
        return not self.truncated and not self.silent and not self.unexpected

    @property
    def shortfall(self) -> tuple[str, ...]:
        """Every reason this proof cannot promote anything, as the names that make it actionable."""
        reasons = [f'truncated by {reason}' for reason in self.truncated]
        reasons.extend(f'silent: {node}' for node in self.silent)
        reasons.extend(f'unselected: {node}' for node in self.unexpected)
        return tuple(reasons)

    @property
    def refusal(self) -> str:
        """One sentence a runner can print instead of a verdict. Empty when the proof holds."""
        if self.complete:
            return ''
        return (
            f'{len(self.selected)} node(s) selected and the run did not cover them: '
            f'{"; ".join(self.shortfall)}. A run that does not cover its selector cannot be '
            f'promoted -- it starts INCONCLUSIVE and stays there.'
        )


@dataclass(frozen=True, slots=True)
class Result:
    """The outcome of a run, its proof, and -- when it could not settle -- why in its own words.

    THE CONSTRUCTOR IS GUARDED RATHER THAN HIDDEN, and NEITHER ROUTE LETS A CALLER ASK FOR PASS: a
    caller states the failures it OBSERVED, and PASS is what remains when there are none and the
    proof holds. Guarding the constructor rather than only offering classmethods is the point --
    a dataclass whose invariants live in its convenience constructors is a declaration the
    constructor does not enforce, and every attribute here is one a caller could otherwise set.
    """

    outcome: Outcome
    proof: Proof | None = None
    failures: tuple[str, ...] = ()
    reason: str = ''

    def __post_init__(self) -> None:
        if not self.outcome.settled:
            self._check_inconclusive()
            return
        self._check_settled()

    def _check_inconclusive(self) -> None:
        """An unsettled result must say WHY, and must not be holding a proof that settles it."""
        if self.proof is not None and self.proof.complete:
            msg = (
                f'this result is {Outcome.INCONCLUSIVE.value} while carrying a COMPLETE proof, so '
                f'the answer was available and was not taken. A result that refuses to conclude '
                f'over sufficient evidence is a declaration that lies.'
            )
            raise IncompleteRun(msg)
        if not self.reason.strip():
            msg = (
                f'{Outcome.INCONCLUSIVE.value} with no reason is indistinguishable from an error '
                f'message with the error removed. State which node ids stayed silent, or which '
                f'truncation fired -- "cannot say" is only information once it says what it is.'
            )
            raise ValueError(msg)
        if self.failures:
            msg = (
                f'this result is {Outcome.INCONCLUSIVE.value} and names {len(self.failures)} '
                f'failure(s). Either the run covered its selector and this is a FAIL naming them, '
                f'or it did not and nothing failed that can be attributed yet.'
            )
            raise IncompleteRun(msg)

    def _check_settled(self) -> None:
        """A settled result needs a complete proof, and failures consistent with its outcome."""
        if self.proof is None or not self.proof.complete:
            why = 'No proof was supplied.' if self.proof is None else self.proof.refusal
            msg = (
                f'{self.outcome.value} cannot be claimed for this run: {why} Promotion out of '
                f'{Outcome.INCONCLUSIVE.value} requires PROOF of completeness, because the default '
                f'must be the answer a new way of running incompletely degrades to.'
            )
            raise IncompleteRun(msg)
        if self.outcome is Outcome.PASS and self.failures:
            msg = (
                f'{Outcome.PASS.value} with {len(self.failures)} named failure(s) '
                f'({", ".join(self.failures)}). PASS is the absence of failures that were observed, '
                f'not a value a caller may assert independently of them.'
            )
            raise IncompleteRun(msg)
        if self.outcome is Outcome.FAIL and not self.failures:
            msg = (
                f'{Outcome.FAIL.value} names no failure, so there is nothing to act on. A red '
                f'verdict that cannot say which test was red is the same refusal a count pin is.'
            )
            raise IncompleteRun(msg)
        unattributed = tuple(node for node in self.failures if node not in self.proof.reported)
        if unattributed:
            msg = (
                f'{", ".join(unattributed)} is named as a failure but never reported an outcome, so '
                f'it failed something the run may never have reached. A failure has to be a node '
                f'that ran.'
            )
            raise IncompleteRun(msg)

    @classmethod
    def inconclusive(cls, reason: str, *, proof: Proof | None = None) -> Result:
        """The honest default. *reason* is required and travels with the result."""
        return cls(outcome=Outcome.INCONCLUSIVE, proof=proof, reason=reason)

    @classmethod
    def settled(cls, *, proof: Proof, failures: Iterable[str] = ()) -> Result:
        """Promote to PASS or FAIL from the failures OBSERVED -- never from a caller's assertion.

        Raises:
            IncompleteRun: *proof* does not hold, so nothing may be promoted.

        """
        named = tuple(sorted(set(failures)))
        return cls(outcome=Outcome.FAIL if named else Outcome.PASS, proof=proof, failures=named)

    def render(self) -> str:
        """One line a report prints. Never the only place the fact is available."""
        tail = self.reason if not self.outcome.settled else (f'({len(self.failures)} failed)' if self.failures else '')
        return f'{self.outcome.value}{f" {tail}" if tail else ""}'


@dataclass(frozen=True, slots=True)
class Verdict:
    """``(tree, env, selector, result, log)`` -- a run's conclusion, with its own evidence.

    All five are required, and the log must already exist and be non-empty when the verdict is
    built: a verdict whose evidence is missing is a claim, and this type exists to make the two
    distinguishable. :meth:`stamp` appends :meth:`line` to that log, which is how a reader who was
    not there finds it -- there is no central verdict store and no citation protocol.
    """

    tree: str
    env: str
    selector: Selector
    result: Result
    log: LogRef

    def __post_init__(self) -> None:
        if not self.tree.strip() or not self.env.strip():
            msg = (
                'a verdict must name the tree and the environment it was earned in. A different '
                'tree or a different resolved environment means the verdict does not EXIST -- not '
                'that it is stale -- so neither can be filled in later.'
            )
            raise ValueError(msg)

    def line(self) -> str:
        """The stamped line: the five fields, one per token, greppable and parseable.

        ``selector`` is LAST and takes the rest of the line, so a spec containing spaces (a node id
        list, a path) round-trips without a quoting rule a reader would have to know.
        """
        return (
            f'{MARKER}result={self.result.outcome.value} tree={self.tree} env={self.env} '
            f'log={self.log.digest}@{self.log.lines} selector={self.selector.spec}'
        )

    def stamp(self) -> None:
        """Append this verdict to its own log, after re-proving the log has NOT moved under it.

        The re-proof is the point: a suite that edits its own log while it runs would otherwise
        stamp a verdict whose evidence no longer matches the digest it carries, and the stamp is
        the only artifact a later reader gets.
        """
        self.log.verify()
        with self.log.path.open('a', encoding='utf-8') as handle:
            handle.write(self.line() + '\n')
