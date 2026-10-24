"""THE DEPENDENCY DOOR IS WIRED -- the assertion half, shared, over :mod:`dev_lab.dev.dep`.

:mod:`dev_lab.dev.dep` has published the MECHANISM since it landed: ``Port``, ``mutate``, the two
gap sentences, the refusal, the retirement. What stayed forked was the eight-arm test that DRIVES it.
MEASURED 2026-09-19 by two independent audit lanes that did not know of each other, one in consumer-b
and one in consumer-c: their copies of ``tests/architecture/test_the_dependency_door_is_wired.py``
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
* *port* -- the repo's own port FACTORY, called with no argument.
* *verdict_anchors* -- the repo's anchor adapter, so the floor arms below judge the repo's reader
  rather than the kit's.

WHO MAY BLOCK A CHANGE IS NOT A REPO ANSWER. It is whoever holds the TARGET environment's
:class:`~dev_lab.dev.envseat.EnvironmentSeat`, read by the door itself; the refusal arms plant a
holder on that seat and, on the other side, on an unrelated environment that must not refuse.
* *anchor_glob* -- the repo-relative name shape its verdict logs take. Spelled by the repo because
  only the repo knows what its ``verify`` writes; the retirement arms are worthless if they retire a
  shape it never produces.
* *anchor* / *tree* / *elsewhere* -- the case's own doubles and the tree being read, supplied per arm.

A *root* BULLET STOOD HERE UNTIL 2026-09-19 AND NAMED A KEYWORD NO FUNCTION IN THIS MODULE TAKES.
None of the seven ``assert_*`` bodies has ever had a ``root`` parameter; the argument belongs to
a famtest of the box seat since retired, whose own docstring carried the same sentence verbatim --
so the line was a paragraph that travelled
between two modules rather than a claim anybody checked. It cost no red, because a docstring
naming an argument that does not exist raises nothing; a consumer lane found it by trying to PASS
it. This is the dominant defect in this codebase's own words -- a declaration asserting a property
the code does not have -- sitting inside the package written to refuse exactly that.

THE GAP SET IS PINNED AS A NAMED SET, both directions, and never as a count. :data:`UNDECLARED_GAPS`
is the set the control must render and the set the repo's own port must render none of.

THE CONTROL IS NOT OPTIONAL AND TAKES NO ARGUMENT.
:func:`assert_a_port_declaring_no_anchors_renders_the_gap` PLANTS a port that declares no anchors
and drives the REAL ``mutate``. Without it, the property arm passes on a door that renders nothing at
all -- which is the state every repo in this family was in until 2026-09-17, reading green throughout.

NOTHING HERE INSTALLS ANYTHING. Every call is either ``dry_run=True`` or is handed :class:`Ran`, a
stand-in for :func:`subprocess.run` that records its argv and installs nothing.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Final

from dev_lab.dev.dep import (
    NO_ANCHORS_DECLARED,
    HeldEnvironmentError,
    Port,
    mutate,
)
from dev_lab.dev.envseat import EnvironmentSeat

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from pathlib import Path

__all__ = [
    'A_REQUIREMENT',
    'UNDECLARED_GAPS',
    'Ran',
    'assert_a_moved_key_retires_a_planted_anchor',
    'assert_a_port_declaring_no_anchors_renders_the_gap',
    'assert_a_verdict_in_another_environment_does_not_refuse',
    'assert_an_unmoved_key_retires_nothing',
    'assert_the_anchor_reader_has_a_floor_and_a_ceiling',
    'assert_the_door_refuses_while_a_verdict_is_in_flight',
    'assert_this_repo_declares_its_verdict_anchors',
    'scripted_keys',
]

#: The sentences the door renders for what a repo left undeclared, as a NAMED SET.
UNDECLARED_GAPS: Final[frozenset[str]] = frozenset({NO_ANCHORS_DECLARED})

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
    past would make :attr:`dev_lab.dev.dep.Report.argv` a declaration that lies, and that report
    is the only thing a reader ever sees.
    """

    def __init__(self, returncode: int = 0) -> None:
        """Answer *returncode* to every call, and record what each one was handed."""
        self.returncode = returncode
        self.stdout = self.stderr = ''  # the streams netverb classifies a resolving command by
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **_: object) -> Ran:
        """Record the argv and answer as a completed process would."""
        self.calls.append(argv)
        return self


#: The census every planted arm hands the door: no other process runs from the planted environment.
#: A consumer suite runs these arms beside its own workers, which all execute from the real venv; the
#: live-process refusal is its own arm in the kit (`test_a_live_process_executing_from_the_environment_refuses`).
def no_other_process() -> tuple[()]:
    """No process runs from the planted environment (the census every planted arm hands the door)."""
    return ()


def scripted_keys(*values: str) -> Callable[[], str]:
    """An ``env_key`` reading a scripted sequence, so a MOVE is plantable without an install.

    The last value repeats, so a port called more often than the script is long answers a settled
    environment rather than raising ``StopIteration`` from inside the door.
    """
    sequence = iter(values)
    last = values[-1]
    return lambda: next(sequence, last)


def assert_this_repo_declares_its_verdict_anchors(
    *,
    port: Callable[[], Port],
    repo_name: str,
) -> None:
    """THE PROPERTY. A report from THIS repo's port renders no gap, and says who changed what.

    Args:
        port: the repo's port factory, called with no argument.
        repo_name: what the report must call this repo.

    Raises:
        AssertionError: a gap was rendered, or the report does not name the repo and the command.

    """
    report = mutate(A_REQUIREMENT, port=port(), dry_run=True, census=no_other_process)
    if report.gaps:
        msg = (
            f'the door rendered {list(report.gaps)} for {repo_name}. A gap here is not cosmetic: '
            f'NO_ANCHORS_DECLARED means a verdict citing a dead environment stays on record.'
        )
        raise AssertionError(msg)
    rendered = report.render()
    if repo_name not in rendered or ' pip install ' not in rendered:  # `-m pip` or `uv pip`
        msg = (
            f'the report does not say who changed what -- expected {repo_name!r} and the pip '
            f'command in:\n{rendered}\nA reader deciding whether to stop their own run has only '
            f'this text to decide on.'
        )
        raise AssertionError(msg)


def assert_a_port_declaring_no_anchors_renders_the_gap() -> None:
    """THE PLANTED CONTROL, driving the REAL door: a port declaring no anchors renders every gap.

    This is the arm that makes the property arm mean anything. Without it, a ``mutate`` that rendered
    nothing at all -- for any reason, including a scanner that never looked -- passes.

    The comparison is a SET EQUALITY, so a door that rendered one gap and swallowed the other reds
    here and names which one it lost. A ``>=`` would be satisfied by every shorter answer, which is
    the under-declaration this family has already paid for six times over.

    Raises:
        AssertionError: the control port rendered a gap set other than :data:`UNDECLARED_GAPS`.

    """
    report = mutate(
        A_REQUIREMENT, port=Port(name='a-repo-that-declares-no-anchors'), dry_run=True, census=no_other_process
    )
    rendered = frozenset(report.gaps)
    if rendered != UNDECLARED_GAPS:
        missing = sorted(gap.split(':')[0] for gap in UNDECLARED_GAPS - rendered)
        extra = sorted(gap.split(':')[0] for gap in rendered - UNDECLARED_GAPS)
        msg = (
            f'a port answering NEITHER question rendered {len(rendered)} gap(s). Not rendered: '
            f'{missing}; rendered and not pinned: {extra}. A gap that is not printed is a gap that '
            f'is assumed away, and this arm is the only thing standing between the property arm and '
            f'a door that renders nothing at all.'
        )
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
    port = Port(name=repo_name, anchor_paths=verdict_anchors)
    try:
        with EnvironmentSeat(sys.prefix, holder).held():
            mutate(A_REQUIREMENT, port=port, dry_run=True, census=no_other_process)
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


def assert_a_verdict_in_another_environment_does_not_refuse(
    *,
    repo_name: str,
    verdict_anchors: Callable[[], Sequence[Path]],
    elsewhere: Path,
) -> None:
    """THE OTHER SIDE OF H1: a verdict holding an UNRELATED environment never refuses this one.

    A guard keyed on the machine rather than on the environment refuses a sync of repo B because a
    verify runs in repo A -- the over-broad denial that teaches agents to route around the door.

    Args:
        repo_name: what the port calls this repo.
        verdict_anchors: the repo's anchor adapter.
        elsewhere: the prefix of an environment that is not this interpreter's.

    Raises:
        AssertionError: the door refused while only another environment was held.

    """
    holder = f'verify:another-repo-than-{repo_name}'
    try:
        with EnvironmentSeat(elsewhere, holder).held():
            mutate(
                A_REQUIREMENT,
                port=Port(name=repo_name, anchor_paths=verdict_anchors),
                dry_run=True,
                census=no_other_process,
            )
    except HeldEnvironmentError as refusal:
        msg = f'the door refused a change to this environment because {holder} held {elsewhere}: {refusal}'
        raise AssertionError(msg) from None


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
        anchor_paths=verdict_anchors,
        key=scripted_keys('before', 'after'),
    )
    report = mutate(A_REQUIREMENT, port=moved, run=Ran(), census=no_other_process)
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
        anchor_paths=verdict_anchors,
        key=scripted_keys('same', 'same'),
    )
    report = mutate(A_REQUIREMENT, port=still, run=Ran(), census=no_other_process)
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
