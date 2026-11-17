"""The files a retirement declared gone -- DATA each checkout declares, read here, held by nobody else.

``STRAY-FILE-REFUSED`` (:mod:`dev_lab.dev.codeplace`) names a stray copy of a retired file with the door that
deletes it, never ``git add`` (2026-11-17: twelve stale indexes a tool had retired, eleven under ``src/``, were
told to be staged). WHICH files are retired is a fact of the checkout that used the retiring tool, so the rows
live in its own ``[tool.dev_lab.placement]`` and arrive here as an argument::

    retired = [
        { path = '<path every copy ends with>', what = '<what it was>', door = '<how to delete it>' },
    ]

The leaf holds no row of its own: a consumer's tree path is that consumer's to hold (:mod:`dev_lab.dev.foreign`),
and a checkout declaring none gets no retired exit -- its strays are judged as any other.
"""

from __future__ import annotations

import dataclasses

__all__ = ['RetiredFile', 'declared_retired']


@dataclasses.dataclass(frozen=True)
class RetiredFile:
    """One declared row: the path every copy ends with, what the file was, and the door that deletes it."""

    path: str
    what: str
    door: str

    def matches(self, rel: str) -> bool:
        """Whether repo-relative POSIX *rel* is a copy of this file, at the root or at any depth below it."""
        return rel == self.path or rel.endswith(f'/{self.path}')


#: The keys of one declared row, exactly: :class:`RetiredFile`'s own fields.
_FIELDS = tuple(sorted(field.name for field in dataclasses.fields(RetiredFile)))


def declared_retired(rows: object) -> tuple[RetiredFile, ...]:
    """The rows of a declared ``retired`` list, each one table with exactly the :class:`RetiredFile` fields.

    Raises:
        ValueError: *rows* is not a list of such tables, or a field is not a non-empty string; the message
            names the shape, so the declaration is fixed rather than read as no rows.

    """
    if isinstance(rows, list) and all(_row(one) for one in rows):
        return tuple(RetiredFile(**one) for one in rows)
    shape = ', '.join(f'{key} = <text>' for key in _FIELDS)
    msg = f'retired is {rows!r}; it must be a list of {{ {shape} }} rows, each field a non-empty string'
    raise ValueError(msg)


def _row(one: object) -> bool:
    return (
        isinstance(one, dict)
        and tuple(sorted(one)) == _FIELDS
        and all(isinstance(value, str) and value.strip() for value in one.values())
    )
