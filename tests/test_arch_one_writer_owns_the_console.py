"""ONE WRITER OWNS THE CONSOLE, so one fix can own its encoding.

WHY THIS GUARD EXISTS, MEASURED 2026-09-18 on wdg-lab. ``lab_commons.dev.verify._tee`` streamed a
test's U+2713 to a cp1252 stdout -- the Windows DEFAULT whenever nothing overrides it -- and
:func:`lab_commons.log.emit` raised ``UnicodeEncodeError`` out through the verdict runner. The run
then produced AN INCONCLUSIVE WITH NO LOG: the one state that proves nothing and carries no verdict.
A kit defect here does not corrupt one answer, it removes the ability to answer, for whatever test
happened to print a character the console cannot carry.

THE FIX IS IN ``emit`` AND THIS IS WHAT KEEPS IT THERE. Twenty-three other call sites across six
modules wrote to ``sys.stdout``/``sys.stderr`` directly on the day this was written, each of them
one non-cp1252 character away from the same crash, and a fix to one while three siblings keep the
defect is the shape this migration exists to remove. They now go through ``emit``, and this guard is
the ratchet: a module that reaches past it owns an encoding it did not choose, so the kit would
again have several answers to the same question.

WHAT THE SET IS, AND WHY IT IS NAMED. The corpus is every tracked module under ``src/``; the
offenders are reported as a NAMED SET of ``module:line`` sites rather than a count, because a count
cannot say WHICH writer came back and invites being edited when it disagrees.
:mod:`lab_commons.log` itself is the one permitted writer and is named here as data.

BOTH SIDES OF THE FLOOR are bound through :mod:`lab_commons.dev.floors`: the low side so an empty
scan is not read as a clean one, and the high side so the floor cannot be outgrown into a waiver
nothing uses.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _arch_corpus import parse, rel, source_modules

from lab_commons.dev.floors import assert_floor, assert_floor_still_binds

#: The only module allowed to hold a real stream. Every other writer borrows it through ``emit``.
THE_ONE_WRITER = 'src/lab_commons/log.py'

#: The streams whose encoding this library never chooses -- it is the terminal's, or the pipe's.
NOT_OURS = ('stdout', 'stderr')

#: RE-MEASURED 2026-09-19: 117 tracked modules under ``src/``, and BOTH NUMBERS STAY ON RECORD.
#: The row above read "MEASURED 2026-09-18: 88" and the tree held 111 that day -- a stored reading
#: that had already stopped agreeing with its derivation, which is precisely what
#: :mod:`lab_commons.dev.famtests.storedreadings` (landed in this same merge) exists to convict.
#: The floor was not repriced with it, so the headroom absorbed the drift silently until the merge
#: that added six modules pushed the scan 47 clear of a 45 headroom and the arm finally said so.
#:
#: SET BELOW THE MEASUREMENT ON PURPOSE, the same shape as before: a floor refuses an UNREAD tree
#: and is not a second pin on the count, so it carries room for ordinary deletion. THE HEADROOM IS
#: UNCHANGED AT 45, and that is the half worth checking -- raising the floor TIGHTENS what a walk
#: must read, while raising the headroom would widen the waiver, which is the move this guard's own
#: docstring calls giving up the arm to keep it.
MODULE_FLOOR = 95
MODULE_HEADROOM = 45


def _writes_a_stream(node: ast.AST) -> bool:
    """``sys.stdout.write(...)`` / ``sys.stderr.write(...)`` -- the shape, not a spelling."""
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'write':
        return False
    owner = node.func.value
    return isinstance(owner, ast.Attribute) and owner.attr in NOT_OURS


def _is_print(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'print'


def _name(path: Path) -> str:
    """The repo-relative spelling every refusal uses; a planted file outside the tree keeps its own."""
    try:
        return rel(path)
    except ValueError:
        return path.name


def unowned_console_writes(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every site outside :data:`THE_ONE_WRITER` that writes text to a stream it did not open."""
    out: list[str] = []
    for path in paths:
        name = _name(path)
        if name == THE_ONE_WRITER:
            continue
        out.extend(
            f'{name}:{node.lineno}' for node in ast.walk(parse(path)) if _writes_a_stream(node) or _is_print(node)
        )
    return tuple(sorted(out))


def test_every_console_write_in_the_kit_goes_through_emit() -> None:
    """THE CHECK, over this repo's own source tree."""
    modules = source_modules()
    assert_floor(len(modules), floor=MODULE_FLOOR, what='console-writer')
    assert_floor_still_binds(len(modules), floor=MODULE_FLOOR, headroom=MODULE_HEADROOM, what='console-writer')
    sites = unowned_console_writes(modules)
    assert sites == (), (
        'these sites write text to a stream whose encoding the kit did not choose, so each of them '
        'can raise UnicodeEncodeError and take the run down with no verdict and no log. Route them '
        'through lab_commons.log.emit:\n  ' + '\n  '.join(sites)
    )


def test_a_planted_raw_stream_write_is_refused(tmp_path: Path) -> None:
    """THE PLANTED CONTROL -- the real scanner, over a module that reaches past ``emit``."""
    offender = tmp_path / 'loud.py'
    offender.write_text('import sys\n\n\ndef shout() -> None:\n    sys.stdout.write("hi\\n")\n', encoding='utf-8')
    clean = tmp_path / 'quiet.py'
    clean.write_text('from lab_commons.log import emit\n\n\ndef shout() -> None:\n    emit("hi")\n', encoding='utf-8')

    assert unowned_console_writes((clean,)) == ()
    found = unowned_console_writes((offender,))
    assert len(found) == 1
    assert found[0].endswith(':5')
