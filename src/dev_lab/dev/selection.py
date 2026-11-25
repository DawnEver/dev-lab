"""WHAT A VERIFY ARGV SELECTS -- read off the arguments before anything runs.

:func:`is_targeted` decides whether a run is a bounded measure (it names a path) or the whole suite,
which only the producer ``forge serve`` spawns may run (:func:`dev_lab.dev.producer.full_suite_refusal`);
a selected path the tree lacks is named by :func:`missing_paths` before anything runs;
:func:`census_scope` decides whether a run may claim the full-suite skip census.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ['census_scope', 'is_targeted', 'missing_paths']


def is_targeted(root: Path, pytest_args: tuple[str, ...]) -> bool:
    """Whether the arguments NAME a path or node in *root* -- a bounded measure -- rather than the whole suite.

    Read off the tree rather than off pytest's grammar: ``-k``/``-m`` narrow a FULL collection and still
    collect everything, so only an argument naming a file or directory that exists makes a run targeted --
    and never the VALUE of an option that takes one (``-k tests`` names no path).
    """
    values = {i + 1 for i, arg in enumerate(pytest_args) if arg in _VALUED_OPTIONS}
    return any(
        i not in values and not arg.startswith('-') and (root / arg.split('::')[0]).exists()
        for i, arg in enumerate(pytest_args)
    )


def missing_paths(root: Path, pytest_args: tuple[str, ...]) -> tuple[str, ...]:
    """Each SELECTED path (its ``::`` node part dropped) that does not exist in *root*, in argv order.

    A selected path is a positional argument, never an option or an option's VALUE (:data:`_VALUED_OPTIONS`).
    Without this a path present only on another branch selects nothing, the run reads as untargeted, and the
    refusal it meets is the full-suite rule -- naming the wrong cause.
    """
    values = {i + 1 for i, arg in enumerate(pytest_args) if arg in _VALUED_OPTIONS}
    paths = (arg.split('::')[0] for i, arg in enumerate(pytest_args) if i not in values and not arg.startswith('-'))
    return tuple(dict.fromkeys(path for path in paths if not (root / path).exists()))


#: The pytest options whose next argument is their value, not a selection.
_VALUED_OPTIONS: Final = frozenset(
    {'-k', '-m', '-p', '-o', '-c', '--deselect', '--ignore', '--rootdir', '--confcutdir'}
)


def census_scope(arguments: tuple[str, ...]) -> tuple[bool, tuple[str, ...]]:
    """Only known presentation flags preserve a full-suite skip census.

    This is not a pytest parser: it recognizes selection and the few display-only flags whose
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
