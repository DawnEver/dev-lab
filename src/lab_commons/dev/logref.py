"""The log a verdict carries: what a reader who was NOT there can check.

A verdict on its own is a claim. Everything that makes it checkable -- what the selector expanded
to, how much of it reported, which environment, which tree -- is what the run PRINTED while it was
happening, so a verdict without its log is an assertion with no evidence attached and no way to
attach any later. That asymmetry is why the log is a REQUIRED part of the verdict rather than
metadata beside it.

THE STAMP AND THE DIGEST ARE ONE OBJECT, and the digest covers the log UP TO the stamped line. That
ordering is the only one that closes: a digest of a file that contains its own digest is a fixed
point nobody can compute. So a reader reads the LAST stamped line, takes the ``<digest>@<lines>``
it names, re-hashes that many lines, and compares -- :func:`verify_log` is that reader, and it is
here rather than in a consumer because a check written by each consumer is a check that each
consumer gets subtly wrong.

A LOG WITH NO STAMPED LINE IS REFUSED, and so is one whose lines moved. The alternative -- returning
what it can and letting the caller notice -- is the shape where a truncated run reads as a clean
one, which is the single defect this whole layer exists to end.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

__all__ = ['MARKER', 'Citation', 'LogRef', 'UnverifiableLog', 'stamp_line', 'verify_log']

#: The one marker line a stamped verdict appends to its own log. Grepping for a token rather than
#: parsing a whole log is deliberate: everything else in the log is prose from whatever ran, and a
#: reader must not have to know its grammar to find the conclusion.
MARKER: Final = 'VERDICT '

#: THE READER OF THE GRAMMAR :func:`stamp_line` WRITES, built FROM :data:`MARKER` rather than
#: beside it, and living in the same module as its producer. It used to spell ``^VERDICT `` as a
#: regex literal while :meth:`lab_commons.dev.verdict.Verdict.line` pasted :data:`MARKER` into an
#: f-string of its own -- two spellings of one grammar in two modules, neither obliged to follow
#: the other when either moved. That is not hypothetical: motronics measured it on 2026-08-21,
#: when a consumer still grepping the previous stamp matched NOTHING and reported "no verdict" for
#: every commit, which is indistinguishable from a box where no gate had ever run. The READER
#: MOVES NEXT TO THE WRITER, so the two cannot drift even in principle.
_STAMPED: Final = re.compile(
    '^' + re.escape(MARKER) + r'result=(?P<result>\w+) tree=(?P<tree>\S+) env=(?P<env>\S+) '
    r'log=(?P<digest>\S+)@(?P<lines>\d+) selector=(?P<spec>.*)$'
)


def stamp_line(*, result: str, tree: str, env: str, digest: str, lines: int, spec: str) -> str:
    """The stamped line: the five fields, one per token, greppable and parseable.

    THE WRITER, and it lives beside :data:`_STAMPED`, which is its inverse. Exported so that
    :meth:`lab_commons.dev.verdict.Verdict.line` keeps no f-string of its own to hold in step --
    a grammar whose producer is in one module and whose consumer is in another is exactly the
    drift this pair exists to make impossible.

    ``spec`` is LAST and takes the rest of the line, so a spec containing spaces (a node id list,
    a path) round-trips without a quoting rule a reader would have to know.
    """
    return f'{MARKER}result={result} tree={tree} env={env} log={digest}@{lines} selector={spec}'


class UnverifiableLog(RuntimeError):
    """A log a verdict names cannot be read, holds no stamp, or no longer hashes to its stamp.

    NOT DEGRADED TO A WARNING. ``.claude/rules/taste.md``: "a warning on an unchanged success
    return is the forbidden shape -- the test is whether the CALLER can tell." A log that moved is
    a verdict whose evidence is gone, and the remedy (re-run) is different in kind from the remedy
    for a red result (fix the code), so the two must not arrive as the same return value.
    """


@dataclass(frozen=True, slots=True)
class LogRef:
    """A log as it stood when a verdict was stamped: where it is, how long, and its digest.

    ``lines`` is carried beside the digest rather than derived at read time, because the reader's
    question is "do the FIRST *lines* lines still hash to this" -- and a reader who re-derived the
    count from the file as it is NOW would always agree with itself.
    """

    path: Path
    digest: str
    lines: int

    @classmethod
    def of(cls, path: Path, *, algorithm: str = 'sha256') -> LogRef:
        """The reference to *path* as it stands now.

        Raises:
            UnverifiableLog: *path* cannot be read, or is EMPTY. An empty log was reached by a run
                that said nothing, and a verdict resting on it would rest on nothing.

        """
        raw = _read(path)
        lines = _split(raw)
        if not lines:
            msg = (
                f'{path} is empty, so a verdict stamped against it would carry no evidence. An '
                f'empty log is a run that said nothing, which is not the same as a run that found '
                f'nothing wrong.'
            )
            raise UnverifiableLog(msg)
        return cls(path=path, digest=_digest_of(lines, algorithm), lines=len(lines))

    def verify(self) -> None:
        """Refuse if the log no longer starts with exactly the bytes this reference digested."""
        raw = _read(self.path)
        lines = _split(raw)
        actual = _digest_of(lines[: self.lines], _algorithm_of(self.digest))
        if actual != self.digest:
            msg = (
                f'{self.path} no longer hashes to {self.digest} over its first {self.lines} lines '
                f'(it is now {actual}). The log a verdict names is its evidence; once it has moved, '
                f'the verdict cannot be checked by anyone who was not there, so it is not citable.'
            )
            raise UnverifiableLog(msg)


@dataclass(frozen=True, slots=True)
class Citation:
    """A verdict as read back OUT of its own log, with the log re-checked against its stamp.

    Deliberately not a :class:`~lab_commons.dev.verdict.Verdict`: the stamp line carries what a
    reader can VERIFY (which tree, which environment, which selector spec, which outcome) and not
    the in-process evidence the run held, which no log can carry and nobody needed it to.
    """

    result: str
    tree: str
    env: str
    spec: str
    log: LogRef


def _algorithm_of(digest: str) -> str:
    """The algorithm out of a ``<algorithm>:<hex>`` digest. ``sha256`` for a bare one."""
    algorithm, separator, _ = digest.partition(':')
    return algorithm if separator else 'sha256'


def _read(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        msg = f'the log a verdict names cannot be read: {path} ({exc}). Its evidence is not lost, it is absent.'
        raise UnverifiableLog(msg) from exc


def _split(raw: bytes) -> list[bytes]:
    """The log's lines, newline INCLUDED, so re-joining a prefix reproduces the original bytes."""
    return raw.splitlines(keepends=True)


def _digest_of(lines: list[bytes], algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    for line in lines:
        digest.update(line)
    return f'{algorithm}:{digest.hexdigest()}'


def _stamped(text: str) -> re.Match[str] | None:
    for line in reversed(text.splitlines()):
        if line.startswith(MARKER):
            return _STAMPED.match(line.strip())
    return None


def verify_log(path: Path) -> Citation:
    """Read the LAST stamped verdict out of *path* and prove the log still earns it.

    The reader's whole interface, and it is one call because the three steps -- find the stamp,
    trust nothing in it, re-hash what it names -- are worthless apart. A reader who finds the stamp
    and stops has believed a line a text editor could have written.

    Raises:
        UnverifiableLog: no stamp, an unparseable one, or a digest that disagrees with the log.

    """
    raw = _read(path)
    text = raw.decode('utf-8', errors='replace')
    match = _stamped(text)
    if match is None:
        msg = (
            f'{path} carries no line beginning {MARKER!r}, so it is not a log a verdict was stamped '
            f'into. A run that produced results WROTE NO VERDICT -- which is the state this layer '
            f'exists to keep distinguishable from a pass.'
        )
        raise UnverifiableLog(msg)
    named = match.group('digest')
    lines = int(match.group('lines'))
    reference = LogRef(path=path, digest=named, lines=lines)
    actual = _digest_of(_split(raw)[:lines], _algorithm_of(named))
    if actual != named:
        msg = (
            f'{path} has been changed since it was stamped: its first {lines} lines hash to '
            f'{actual}, and the stamp names {named}. The stamped verdict describes a log that no '
            f'longer exists.'
        )
        raise UnverifiableLog(msg)
    return Citation(
        result=match.group('result'),
        tree=match.group('tree'),
        env=match.group('env'),
        spec=match.group('spec'),
        log=reference,
    )
