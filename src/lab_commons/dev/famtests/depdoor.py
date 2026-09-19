"""THE DEPENDENCY DOOR IS WIRED -- the assertion half, shared, over :mod:`lab_commons.dev.dep`.

:mod:`lab_commons.dev.dep` has published the MECHANISM since it landed: ``Port``, ``mutate``, the two
gap sentences, the refusal, the retirement. What stayed forked was the eight-arm test that DRIVES it.
MEASURED 2026-09-19 by two independent audit lanes that did not know of each other, one in wdg-lab
and one in optimi-lab: their copies of ``tests/architecture/test_the_dependency_door_is_wired.py``
are **91.5% identical**, and a byte diff of the two files says exactly what the 8.5% is --

* a docstring, twice, narrating each repo's own refuted "the rule has no subject here";
* the repo's NAME, four times, in a ``Port(name=...)``, in a planted holder string and in an
  assertion that the rendered report says who changed what;
* a ``tempfile`` prefix and two invented log timestamps, which are not facts about anything.

Nothing else differed -- not one assertion, not one message. So the ASSERTIONS were never per-repo
and the fork was carrying a single noun.

WHAT ARRIVES WITH NO DEFAULT, and why each is one repo's answer rather than a convenience:

* *repo_name* -- what the ``Port`` calls this repo. It is what the report PRINTS, and a report that
  names the wrong repo is read by whoever is deciding whether to stop their own run.
* *port* -- the repo's own port FACTORY, called as ``port(broker=...)``. The factory and not a built
  ``Port``, because the records directory the holders adapter reads has to be the CASE's: this body
  runs inside a ``verify`` run that already holds the real seat, so a real port would refuse here --
  correctly, and before it could report anything.
* *live_holders* / *verdict_anchors* -- the two adapters themselves, so the floor arms below judge
  the repo's readers rather than the kit's.
* *anchor_glob* -- the repo-relative name shape its verdict logs take. Spelled by the repo because
  only the repo knows what its ``verify`` writes; the retirement arms are worthless if they retire a
  shape it never produces.
* *root* -- the checkout being answered for. A guard rooted at the working directory answers,
  plausibly, about somebody else's tree.

THE GAP SET IS PINNED AS A NAMED SET, both directions, and never as a count. An integer cannot say
WHICH half of the door came off, and this family has an incident where a disagreeing pin was edited
down to meet a broken table rather than the other way round. :data:`BOTH_GAPS` is the set the control
must render and the set the repo's own port must render none of.

THE CONTROL IS NOT OPTIONAL AND TAKES NO ARGUMENT.
:func:`assert_a_port_declaring_neither_renders_both_gaps` PLANTS a port that answers neither question
and drives the REAL ``mutate``. Without it, the property arm passes on a door that renders nothing at
all -- which is the state every repo in this family was in until 2026-09-17, reading green throughout.

NOTHING HERE INSTALLS ANYTHING. Every call is either ``dry_run=True`` or is handed :class:`Ran`, a
stand-in for :func:`subprocess.run` that records its argv and installs nothing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from lab_commons.dev.boxlock import BoxLock
from lab_commons.dev.dep import (
    LOCK_UNDECLARED,
    NO_ANCHORS_DECLARED,
    HeldEnvironmentError,
    Port,
    mutate,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

    from lab_commons.resources import Broker

__all__ = [
    'A_REQUIREMENT',
    'BOTH_GAPS',
    'Ran',
    'assert_a_moved_key_retires_a_planted_anchor',
    'assert_a_port_declaring_neither_renders_both_gaps',
    'assert_an_unmoved_key_retires_nothing',
    'assert_the_anchor_reader_has_a_floor_and_a_ceiling',
    'assert_the_door_refuses_while_a_verdict_is_in_flight',
    'assert_the_holders_adapter_names_a_planted_holder',
    'assert_this_repo_supplies_both_halves_of_the_door',
    'scripted_keys',
]

#: The two sentences the door renders for the two halves nobody supplied, as a NAMED SET. A count
#: here would say "one gap" and leave a reader unable to tell an unguarded H1 from an unremediable
#: H2 -- two findings with two different remedies.
BOTH_GAPS: Final[frozenset[str]] = frozenset({LOCK_UNDECLARED, NO_ANCHORS_DECLARED})

#: The requirement every arm names. Nothing is ever installed, but the door REFUSES an empty
#: requirement list -- correctly, since a bare ``pip install`` names no change whose safety to decide
#: -- so a requirement has to exist for the arms to reach the code they are about.
A_REQUIREMENT: Final = ('lab-commons',)

#: The timestamp the floor arm writes into *anchor_glob*. A constant, because the arm is about the
#: SHAPE of the name and a date in it would be a fact about the day the test ran.
_A_TIMESTAMP: Final = '20260919T120000Z'


class Ran:
    """A stand-in for :func:`subprocess.run` that installs NOTHING and reports the code it was given.

    Injected through ``mutate(run=...)``, which is the seam the door publishes for exactly this. The
    argv it was handed is RECORDED rather than composed: a stand-in that appended a flag on the way
    past would make :attr:`lab_commons.dev.dep.Report.argv` a declaration that lies, and that report
    is the only thing a reader ever sees.
    """

    def __init__(self, returncode: int = 0) -> None:
        """Answer *returncode* to every call, and record what each one was handed."""
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: object) -> Ran:
        """Record the argv and answer as a completed process would."""
        self.calls.append(argv)
        return self


def scripted_keys(*values: str) -> Callable[[], str]:
    """An ``env_key`` reading a scripted sequence, so a MOVE is plantable without an install.

    The last value repeats, so a port called more often than the script is long answers a settled
    environment rather than raising ``StopIteration`` from inside the door.
    """
    sequence = iter(values)
    last = values[-1]
    return lambda: next(sequence, last)


def assert_this_repo_supplies_both_halves_of_the_door(
    *,
    port: Callable[..., Port],
    repo_name: str,
    broker: Broker,
) -> None:
    """THE PROPERTY. A report from THIS repo's port renders NEITHER gap, and says who changed what.

    Args:
        port: the repo's port factory, called as ``port(broker=...)``.
        repo_name: what the report must call this repo.
        broker: an ISOLATED records directory. Not squeamishness -- see this module's docstring.

    Raises:
        AssertionError: a gap was rendered, or the report does not name the repo and the command.

    """
    report = mutate(A_REQUIREMENT, port=port(broker=broker), dry_run=True)
    if report.gaps:
        msg = (
            f'the door rendered {list(report.gaps)} for {repo_name}. A gap here is not cosmetic: '
            f'LOCK_UNDECLARED means a dependency change DURING a verdict run is unchecked rather '
            f'than impossible, and NO_ANCHORS_DECLARED means a verdict citing a dead environment '
            f'stays on record.'
        )
        raise AssertionError(msg)
    rendered = report.render()
    if repo_name not in rendered or '-m pip install' not in rendered:
        msg = (
            f'the report does not say who changed what -- expected {repo_name!r} and the pip '
            f'command in:\n{rendered}\nA reader deciding whether to stop their own run has only '
            f'this text to decide on.'
        )
        raise AssertionError(msg)


def assert_a_port_declaring_neither_renders_both_gaps() -> None:
    """THE PLANTED CONTROL, driving the REAL door: a port answering neither question renders BOTH.

    This is the arm that makes the property arm mean anything. Without it, a ``mutate`` that rendered
    nothing at all -- for any reason, including a scanner that never looked -- passes.

    The comparison is a SET EQUALITY, so a door that rendered one gap and swallowed the other reds
    here and names which one it lost. A ``>=`` would be satisfied by every shorter answer, which is
    the under-declaration this family has already paid for six times over.

    Raises:
        AssertionError: the control port rendered a gap set other than :data:`BOTH_GAPS`.

    """
    report = mutate(A_REQUIREMENT, port=Port(name='a-repo-that-declares-neither'), dry_run=True)
    rendered = frozenset(report.gaps)
    if rendered != BOTH_GAPS:
        missing = sorted(gap.split(':')[0] for gap in BOTH_GAPS - rendered)
        extra = sorted(gap.split(':')[0] for gap in rendered - BOTH_GAPS)
        msg = (
            f'a port answering NEITHER question rendered {len(rendered)} gap(s). Not rendered: '
            f'{missing}; rendered and not pinned: {extra}. A gap that is not printed is a gap that '
            f'is assumed away, and this arm is the only thing standing between the property arm and '
            f'a door that renders nothing at all.'
        )
        raise AssertionError(msg)


def assert_the_holders_adapter_names_a_planted_holder(
    *,
    live_holders: Callable[..., Sequence[str]],
    broker: Broker,
) -> None:
    """PLANTED ON THE MACHINE, both sides. An adapter answering "nobody" forever guards nothing.

    The floor is the middle reading: an adapter that returns an empty tuple whatever is happening
    reads as "no verdict is ever in flight", which is a vacuous green the door cannot see through.
    The two empty readings either side are the other half of the ratchet -- an adapter that always
    named somebody would refuse every dependency change this repo will ever make.

    Args:
        live_holders: the repo's own holders adapter, called as ``live_holders(broker=...)``.
        broker: an ISOLATED records directory, so the plant contends only with itself.

    Raises:
        AssertionError: the adapter saw a holder that was not planted, or missed one that was.

    """
    before = tuple(live_holders(broker=broker))
    if before:
        msg = f'a fresh records directory already named {list(before)} as a verdict run'
        raise AssertionError(msg)
    planted = 'verify:the-planted-run'
    with BoxLock(planted, broker=broker).held():
        named = tuple(live_holders(broker=broker))
    if not any(planted in holder for holder in named):
        msg = (
            f'the adapter answered {list(named)} while {planted!r} really held the box. H1 cannot be '
            f'refused by an adapter that cannot see the run it is meant to refuse, and an adapter '
            f'that can never see one is indistinguishable from a repo declaring no lock -- except '
            f'that the repo declaring none is at least reported.'
        )
        raise AssertionError(msg)
    after = tuple(live_holders(broker=broker))
    if after:
        msg = f'the planted holder outlived the block that took it: {list(after)}'
        raise AssertionError(msg)


def assert_the_door_refuses_while_a_verdict_is_in_flight(
    *,
    repo_name: str,
    verdict_anchors: Callable[[], Sequence[Path]],
) -> None:
    """H1, PREVENTED -- and the refusal NAMES the holder, because "busy" cannot be acted on.

    The holder is PLANTED rather than taken, so this arm asserts about the DOOR and never about what
    happens to be running on the box while it reads.

    Args:
        repo_name: what the port calls this repo; it must reach the refusal text.
        verdict_anchors: the repo's anchor adapter, supplied so the refusal is reached through an
            otherwise COMPLETE port -- a refusal that only fires on a half-declared port would be
            measuring the declaration rather than the lock.

    Raises:
        AssertionError: the door did not refuse, or the refusal does not name the holder and the key.

    """
    holder = f'verify:{repo_name} pid=4242'
    held = Port(name=repo_name, holders=lambda: (holder,), anchor_paths=verdict_anchors)
    try:
        mutate(A_REQUIREMENT, port=held, dry_run=True)
    except HeldEnvironmentError as refusal:
        text = str(refusal)
    else:
        msg = (
            f'the door changed the environment while {holder} held a verdict for it. That is H1 '
            f'happening rather than H1 being reported: the verdict cites an environment it did not '
            f'run in, and nothing downstream can tell.'
        )
        raise AssertionError(msg) from None
    if holder not in text or 'env_key' not in text:
        msg = (
            f'the refusal said {text!r}. It must name the HOLDER -- a reader has to choose between '
            f'waiting, stopping the holder and giving up, and only the name separates those three '
            f'-- and it must say WHY a running verdict is at risk, which is the env_key it computes '
            f'when it ends.'
        )
        raise AssertionError(msg)


def assert_a_moved_key_retires_a_planted_anchor(
    *,
    repo_name: str,
    verdict_anchors: Callable[[], Sequence[Path]],
    anchor: Path,
) -> None:
    """H2, REMEDIED. A moved key retires the planted verdict, and the file is GONE from disk.

    Both halves are asserted because either alone is weak: the report is a CLAIM, and a retirement
    that reports a path it did not delete leaves a citable verdict about a dead environment exactly
    where a reader will find it.

    Args:
        repo_name: what the port calls this repo.
        verdict_anchors: the repo's adapter, bound by the caller to the tree *anchor* is in.
        anchor: the planted verdict log, which must already exist.

    Raises:
        AssertionError: the anchor was not planted, the key did not move, or the file survived.

    """
    if not anchor.exists():
        msg = f'{anchor} was never planted, so this arm would retire nothing and pass for it'
        raise AssertionError(msg)
    moved = Port(
        name=repo_name,
        holders=lambda: (),
        anchor_paths=verdict_anchors,
        key=scripted_keys('before', 'after'),
    )
    report = mutate(A_REQUIREMENT, port=moved, run=Ran())
    if not report.moved or report.retired != (str(anchor),):
        msg = (
            f'the env_key moved={report.moved} and {list(report.retired)} was retired, against the '
            f'one planted anchor {anchor}. A verdict citing an environment that no longer exists is '
            f'the thing this half of the door removes.'
        )
        raise AssertionError(msg)
    if anchor.exists():
        msg = f'{anchor} was REPORTED retired and is still on disk; the report is a declaration that lies'
        raise AssertionError(msg)


def assert_an_unmoved_key_retires_nothing(
    *,
    repo_name: str,
    verdict_anchors: Callable[[], Sequence[Path]],
    anchor: Path,
) -> None:
    """THE OTHER SIDE OF THE RATCHET. A retirement that always fires DELETES evidence nobody voided.

    A capability that disappears and a waiver nobody uses are one defect pointing two ways, and a
    door that retired on every call would pass the arm above forever.

    Args:
        repo_name: what the port calls this repo.
        verdict_anchors: the repo's adapter, bound by the caller to the tree *anchor* is in.
        anchor: the planted verdict log, which must exist before AND after.

    Raises:
        AssertionError: the anchor was not planted, the key moved, or the file was deleted.

    """
    if not anchor.exists():
        msg = f'{anchor} was never planted, so a door that deletes everything would pass this arm'
        raise AssertionError(msg)
    still = Port(
        name=repo_name,
        holders=lambda: (),
        anchor_paths=verdict_anchors,
        key=scripted_keys('same', 'same'),
    )
    report = mutate(A_REQUIREMENT, port=still, run=Ran())
    if report.moved or report.retired:
        msg = (
            f'an UNCHANGED environment reported moved={report.moved} and retired '
            f'{list(report.retired)}. A verdict is evidence; deleting one nothing invalidated is the '
            f'same loss as keeping one that was.'
        )
        raise AssertionError(msg)
    if not anchor.exists():
        msg = f'an unchanged environment took the live verdict {anchor} down with it'
        raise AssertionError(msg)


def assert_the_anchor_reader_has_a_floor_and_a_ceiling(
    *,
    verdict_anchors: Callable[[Path], Sequence[Path]],
    anchor_glob: str,
    tree: Path,
) -> None:
    """FLOOR AND CEILING ON THE ANCHOR SCAN: it finds the real shape, and it invents none.

    FINDING NOTHING IS NOT A PASS. Without the floor, every retirement arm above is retiring a shape
    this repo never writes and all of them are green. Without the ceiling, the adapter hands the door
    a stray file to delete.

    Args:
        verdict_anchors: the repo's anchor adapter, taking the tree to read.
        anchor_glob: the repo-relative name shape its verdict logs take; ``*`` is substituted.
        tree: an EMPTY scratch tree. The directory and the files are created here.

    Raises:
        AssertionError: the adapter invented an anchor, or could not see the one really written.

    """
    if any(tree.iterdir()):
        msg = f'{tree} is not empty, so the first reading below is not the empty-tree reading it claims to be'
        raise AssertionError(msg)
    empty = tuple(verdict_anchors(tree))
    if empty:
        msg = f'a tree with no verdict directory reported {list(empty)} as anchors'
        raise AssertionError(msg)
    real = tree / anchor_glob.replace('*', _A_TIMESTAMP)
    real.parent.mkdir(parents=True, exist_ok=True)
    stray = real.parent / 'not-a-verdict.txt'
    stray.write_text('', encoding='utf-8')
    strays = tuple(verdict_anchors(tree))
    if strays:
        msg = f'the stray file {stray} was read as a verdict; the door would have deleted it'
        raise AssertionError(msg)
    real.write_text('VERDICT result=PASS\n', encoding='utf-8')
    found = tuple(verdict_anchors(tree))
    if found != (real,):
        msg = (
            f'the adapter answered {list(found)} for the log name this repo really writes ({real}). '
            f'Every retirement arm above would be retiring a shape that never exists, and every one '
            f'of them would be green.'
        )
        raise AssertionError(msg)
