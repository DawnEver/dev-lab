"""A PARTITION of a population, and the rule that says when partial answers may answer for the whole.

Migrated 2026-09-17 from motronics-studio's ``scripts/gate/_shards.py``. Nothing repo-shaped was
left behind to strip: the population's directory and filename pattern already arrived as arguments
there, and :func:`compose` is handed rows somebody else read and parsed. What changed in the move is
the VOCABULARY -- the outcome is :class:`lab_commons.dev.verdict.Outcome` rather than three bare
strings, because this family already has a total three-state enum and a second spelling of it would
be a fourth state nobody declared.

A MISSING PIECE IS NEVER A PASS, and that is the one opinion here. An incomplete set that answers
for the whole is a verdict about whichever pieces happened to finish. Two measured incidents wear
that shape: 2026-08-17, ten sharded sets, zero complete, a week-old green reported as current; and
2026-08-24, a run that never happened inheriting an answer.

THE POLARITY MATCHES :mod:`lab_commons.dev.verdict` DELIBERATELY. Every refusal below lands on
``INCONCLUSIVE`` rather than on ``FAIL``, because "we cannot say" and "it failed" have different
remedies -- re-run the missing piece, against fix the code -- and a composer that flattened them
would send every reader to the second one.

A POPULATION HAS A FLOOR. A shard set over an empty population reports the same clean numbers as one
over a healthy tree, and each piece then runs nothing and passes: the vacuous green arrives through
the ARITHMETIC rather than through the assertions. :func:`population` therefore takes a required
floor, exactly as :func:`lab_commons.dev.testfacts.collect` does, and raises the same error class so
a consumer has one exception to catch rather than two spellings of one idea.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lab_commons.dev.testfacts import VacuousScanError
from lab_commons.dev.verdict import Outcome

__all__ = ['Composed', 'Row', 'compose', 'partition', 'population']

#: A row is ``(tree, env, outcome)`` as some reader recovered it, or ``None`` when that piece is
#: absent or unreadable. The distinction between "absent" and "unreadable" belongs to the reader;
#: from here both are the same fact -- this piece did not answer.
type Row = tuple[str, str, Outcome] | None


def population(root: Path, subdir: str, pattern: str, *, floor: int) -> tuple[str, ...]:
    """Every file under ``root/subdir`` matching *pattern*, sorted, repo-relative and posix-spelled.

    SORTED so the assignment is DETERMINISTIC across machines and runs: piece 2 of 8 must mean the
    same files everywhere, or two pieces of one set are not describing one job. POSIX-spelled for
    the same reason one step further out -- a member spelled with backslashes on one box and with
    slashes on another is two members as far as any comparison is concerned.

    Args:
        root: the checkout the returned names are relative to.
        subdir: where the population lives beneath it.
        pattern: the ``rglob`` pattern its members match.
        floor: the smallest population size that is not evidence of a broken scan. REQUIRED, and
            there is no sensible default: a moved directory or a renamed pattern yields zero
            members, every shard then runs nothing, and the set composes to PASS.

    Returns:
        The members, sorted.

    Raises:
        VacuousScanError: fewer than *floor* members were found.

    """
    found = tuple(sorted(p.relative_to(root).as_posix() for p in (root / subdir).rglob(pattern)))
    if len(found) < floor:
        msg = (
            f'the population under {subdir}/{pattern} reached only {len(found)} members, below the '
            f'{floor} floor. Sharding an empty population gives every shard nothing to do and every '
            f'shard then passes, so this would compose into a green verdict about no work at all. '
            f'Fix the directory or the pattern; do not lower the floor.'
        )
        raise VacuousScanError(msg)
    return found


def partition(whole: tuple[str, ...], index: int, count: int) -> tuple[str, ...]:
    """The members of piece *index* (0-based) of *count*.

    ROUND-ROBIN over the sorted list rather than contiguous blocks: adjacent files in a directory
    tend to share fixtures and cost, so contiguous slicing puts the expensive neighbourhood in one
    piece and leaves another nearly empty -- and a shard set is only as fast as its slowest piece.

    Raises:
        ValueError: *index* is outside ``0..count-1``, or *count* is not positive. An out-of-range
            index would otherwise return an empty piece, which is a shard that ran nothing and said
            it passed.

    """
    if count < 1:
        msg = f'a shard set has at least one piece and got count={count}'
        raise ValueError(msg)
    if not 0 <= index < count:
        msg = f'shard index {index} is outside 0..{count - 1}'
        raise ValueError(msg)
    return tuple(member for i, member in enumerate(whole) if i % count == index)


@dataclass(frozen=True, slots=True)
class Composed:
    """The composition's answer, and the evidence for it."""

    #: The composed outcome. ``INCONCLUSIVE`` whenever the set cannot answer for the whole.
    result: Outcome
    #: Why, in words a reader who was not there can act on.
    reason: str
    #: How many pieces reported at all.
    present: int
    #: How many pieces the set was supposed to have.
    count: int


def _incomplete(rows: tuple[Row, ...], count: int) -> Composed | None:
    """The first refusal: a set that is short, long, or holding a piece that did not answer."""
    missing = [i for i, row in enumerate(rows) if row is None]
    if not missing and len(rows) == count:
        return None
    present = len([row for row in rows if row is not None])
    where = f'indices {missing}' if missing else f'{len(rows)} rows for a set of {count}'
    return Composed(
        Outcome.INCONCLUSIVE,
        f'{count - present} of {count} shard verdicts did not arrive ({where}) -- an incomplete set '
        f'is not a verdict about the whole, it is a verdict about whichever shards happened to '
        f'finish',
        present,
        count,
    )


def compose(rows: tuple[Row, ...], count: int) -> Composed:
    """AND over a COMPLETE set of rows that all name one ``(tree, env)``.

    THE FOUR REFUSALS, each a way an incomplete or unattributable set could answer for the whole:

    * a MISSING row is INCONCLUSIVE -- never "the ones that arrived all passed";
    * a DISAGREEING tree or env is INCONCLUSIVE, because an answer is a fact about ONE
      ``(tree, env)`` pair and pieces of different ones are not one job;
    * a tree that NAMES NOTHING is INCONCLUSIVE. Two pieces both stamped ``unknown`` -- or both
      ``<sha>-dirty`` -- collapse to one element and pass the agreement check, so a set nobody can
      attribute would compose into an answer about a tree that was never identified. The agreement
      check asks "one tree?"; this asks "a tree at all?";
    * any FAIL makes the whole FAIL, because the question is about the whole.

    The ``-dirty`` and ``unknown`` spellings are matched because they are what a git-shaped stamp
    produces when it cannot answer. A consumer stamping
    :func:`lab_commons.dev.content.content_address` instead never reaches that arm, which is the
    correct behaviour rather than a gap: a content address is never unattributable.

    Args:
        rows: one entry per piece, in piece order, ``None`` where a piece did not answer.
        count: how many pieces the set was supposed to have.

    Returns:
        The composed answer with its evidence.

    """
    short = _incomplete(rows, count)
    if short is not None:
        return short
    settled = [row for row in rows if row is not None]
    trees = {tree for tree, _env, _outcome in settled}
    envs = {env for _tree, env, _outcome in settled}
    if len(trees) != 1 or len(envs) != 1:
        return Composed(
            Outcome.INCONCLUSIVE,
            f'shards disagree about what was judged: tree={sorted(trees)} env={sorted(envs)} -- '
            f'shards of different trees or environments are not one run',
            count,
            count,
        )
    tree = next(iter(trees))
    if tree == 'unknown' or tree.endswith('-dirty'):
        return Composed(
            Outcome.INCONCLUSIVE,
            f'the shards agree on tree={tree}, which names no committed state -- shards measured on '
            f'an unidentifiable or uncommitted tree are not a verdict about a commit',
            count,
            count,
        )
    outcomes = [outcome for _tree, _env, outcome in settled]
    failed = sum(1 for outcome in outcomes if outcome is Outcome.FAIL)
    if failed:
        return Composed(Outcome.FAIL, f'{failed} of {count} shards FAILED', count, count)
    if all(outcome is Outcome.PASS for outcome in outcomes):
        return Composed(Outcome.PASS, f'all {count} shards PASSED over one tree', count, count)
    return Composed(
        Outcome.INCONCLUSIVE,
        f'shard results are {sorted({outcome.value for outcome in outcomes})} -- a set cannot be '
        f'greener than its least conclusive shard',
        count,
        count,
    )
