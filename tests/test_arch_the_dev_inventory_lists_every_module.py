"""DECLARATION-LIES, over the one docstring that presents itself as an inventory.

``lab_commons/dev/__init__.py`` opens with "WHAT IS HERE", a bulleted list of the subpackage's
modules. A reader -- human or model -- takes that list as the surface. Nothing checked it.

MEASURED 2026-09-16, and this is why the guard exists rather than a repair. Listing the directory
against the bullets found THREE public modules with no line: ``devdocs`` (landing that day) and
``boxwait`` and ``dep``, which had landed HOURS earlier in separate commits. A four-agent race on the
file made the gap visible, but the gap PREDATED the race -- the inventory had simply never been
checked, and the check is ``ls``. That is the dominant defect in its cheapest form: a declaration
asserting a property the code does not enforce, where enforcing it costs one test.

TWO-SIDED, as a ratchet must be. A module with no bullet is named; a bullet naming a module that no
longer exists is ALSO named. Without the second half the inventory rots in the other direction -- a
renamed or deleted module leaves a line that reads as a live surface, which is the same lie pointing
the other way.

PRIVATE MODULES ARE EXCLUDED BY SHAPE, AND THE EXCLUSION IS ITSELF A CLAIM, so it is stated here
rather than left to a reader: a leading underscore already says "not part of the surface", and an
inventory of the surface that demanded a line for each of them would be arguing with its own
premise. ``__init__`` is excluded because it IS the document. Computing the exclusion from the
filename rather than from a path list is what stops it rotting into a set somebody widened during a
red suite.
"""

from __future__ import annotations

import re
from pathlib import Path

from _arch_corpus import assert_floor

import lab_commons.dev as dev_pkg

#: The directory the inventory is about.
DEV_DIR = Path(dev_pkg.__file__).resolve().parent

#: A module that is NOT run rather than imported is still expected to be listed -- ``verify``,
#: ``githooks`` and ``docsite`` each carry a bullet that says why they are not re-exported, which is
#: exactly the information the inventory exists to carry. So there is no exemption here at all.
#: MEASURED 2026-09-16: 23 public modules. The floor sits under it, because "every module has a
#: bullet" over an EMPTY list reads exactly like a clean result.
MODULE_FLOOR = 15

#: How the docstring names a module: a Sphinx role over the fully-qualified path.
_BULLET = re.compile(r':mod:`lab_commons\.dev\.([A-Za-z_][A-Za-z0-9_]*)`')


def public_modules(directory: Path) -> tuple[str, ...]:
    """Every public module name under *directory* -- a module, or a package with an ``__init__``."""
    names = {p.stem for p in directory.glob('*.py')} | {
        p.name for p in directory.iterdir() if (p / '__init__.py').is_file()
    }
    return tuple(sorted(n for n in names if not n.startswith('_')))


def inventory_problems(docstring: str, present: tuple[str, ...]) -> tuple[str, ...]:
    """Both sides: a module with no bullet, and a bullet naming a module that is not there.

    Pure over its arguments so the planted control below drives THIS function rather than a second
    implementation that would agree with it by construction.
    """
    listed = set(_BULLET.findall(docstring))
    out = [f'{name}: a public module with no bullet in the dev inventory' for name in sorted(set(present) - listed)]
    out += [f'{name}: the inventory lists it, and no such module is here' for name in sorted(listed - set(present))]
    return tuple(out)


def test_the_dev_inventory_names_every_public_module_and_only_those() -> None:
    """THE CHECK. A module added without its line, or a line outliving its module, reds here."""
    present = public_modules(DEV_DIR)
    assert_floor(len(present), MODULE_FLOOR, 'dev module inventory')
    problems = inventory_problems(dev_pkg.__doc__ or '', present)
    assert problems == (), (
        "lab_commons/dev/__init__.py's inventory disagrees with the directory:\n  "
        + '\n  '.join(problems)
        + '\nAdd the bullet with the module, or delete the bullet with it. An inventory that omits a '
        'module is a declaration that lies about the surface a consumer is importing.'
    )


def test_a_planted_inventory_reds_on_both_sides() -> None:
    """THE PLANTED CONTROL, through the REAL matcher, one side at a time."""
    doc = 'WHAT IS HERE:\n* :mod:`lab_commons.dev.here` -- a real one.\n* :mod:`lab_commons.dev.gone` -- retired.\n'
    problems = inventory_problems(doc, ('here', 'unlisted'))
    assert problems == (
        'unlisted: a public module with no bullet in the dev inventory',
        'gone: the inventory lists it, and no such module is here',
    ), problems
    assert inventory_problems(doc, ('here', 'gone')) == ()


def test_the_scan_reads_this_package_and_excludes_by_shape() -> None:
    """The corpus really is this directory, and the private exclusion is computed rather than listed."""
    present = public_modules(DEV_DIR)
    assert 'rules' in present, present
    assert 'verify' in present, present
    assert not any(name.startswith('_') for name in present), present
    assert '__init__' not in present
