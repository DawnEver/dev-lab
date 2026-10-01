"""A subprocess read in TEXT mode names its encoding, in every module this repo ships or tests with.

``text=True`` without ``encoding=`` decodes with the LOCALE's codec. On a Windows host whose ANSI
codepage is gbk, the first non-ASCII byte git prints -- a commit subject, a path, a docstring read
through ``git show`` -- raises ``UnicodeDecodeError`` inside the reader thread, the call returns
``stdout=None``, and the census reading it reports "no committed pyproject.toml" about a tree that
has one. MEASURED 2026-10-01: 34 tests on this suite failed that way, and every one of them passed
under ``PYTHONUTF8=1`` -- a fix that lives in somebody's environment rather than in the call, so it
holds only for the person who set it. The call is where the decision belongs.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from _arch_corpus import assert_floor, parse, rel, source_modules, suite_modules

#: Keywords that switch a subprocess-shaped call into text mode.
TEXT_SWITCHES = frozenset({'text', 'universal_newlines'})

#: The callees that spawn a process and decode its pipes. ``text`` on anything else is a plain
#: argument (a log distillate, a stored claim) and decodes nothing.
SPAWNERS = frozenset({'run', 'Popen', 'check_output', 'check_call', 'call', 'run_bounded'})

#: MEASURED 2026-10-01: 265 tracked source + suite modules.
MODULE_FLOOR = 240


def _bare_name(func: ast.expr) -> str:
    return func.id if isinstance(func, ast.Name) else ''


def _undeclared(tree: ast.Module) -> list[int]:
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func.attr if isinstance(node.func, ast.Attribute) else _bare_name(node.func)
        names = {kw.arg for kw in node.keywords}
        if callee in SPAWNERS and names & TEXT_SWITCHES and 'encoding' not in names:
            out.append(node.lineno)
    return out


def undeclared_text_calls(paths: tuple[Path, ...]) -> tuple[str, ...]:
    """Every ``text=True`` call with no ``encoding=`` -- pure over its argument."""
    return tuple(f'{rel(path)}:{line}' for path in paths for line in _undeclared(parse(path)))


def test_every_text_mode_call_names_its_encoding() -> None:
    paths = source_modules() + suite_modules()
    assert_floor(len(paths), MODULE_FLOOR, 'text-mode subprocess')
    found = undeclared_text_calls(paths)
    assert not found, f'text-mode calls decoding with the locale codec: {found}'


@pytest.mark.parametrize(
    ('body', 'flagged'),
    [
        ("subprocess.run(['git'], text=True)\n", True),
        ("subprocess.run(['git'], universal_newlines=True)\n", True),
        ('Distillate(text=True)\n', False),
        ("subprocess.run(['git'], text=True, encoding='utf-8', errors='replace')\n", False),
    ],
)
def test_a_planted_locale_decode_is_refused(tmp_path: Path, body: str, *, flagged: bool) -> None:
    planted = tmp_path / 'planted.py'
    planted.write_text(f'import subprocess\n{body}', encoding='utf-8')
    assert bool(_undeclared(ast.parse(planted.read_text(encoding='utf-8')))) is flagged
