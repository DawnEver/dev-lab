"""SERVE CHECKOUTS LIVE IN THE FORGE HOME (user ruling 2026-10-26), never in a user-visible ``~/src``.

A forge serve host once kept its checkouts under ``~/src``: they read as a second set of dev repos, sessions
edited them, and a dev checkout's venv became the Task's kit. The forge's machine home is derived by ONE
function (:func:`dev_lab.dev.servelock.forge_home`); no source module may derive a root from ``home / 'src'``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

from _arch_corpus import SOURCE_FLOOR, assert_floor, parse, rel, source_modules

#: ``~/src`` or ``~\src`` spelled in a string: a checkout root named by hand.
_TILDE_SRC: Final = re.compile(r'~[/\\]src\b')


def _home_call(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Attribute) and node.func.attr in {'home', 'expanduser'})
        or (isinstance(node.func, ast.Name) and node.func.id == 'home')
    )


def _src_root(node: ast.AST) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _home_call(node.left) and isinstance(node.right, ast.Constant) and node.right.value == 'src'
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(_TILDE_SRC.search(node.value))


def _derives_src_root(path: Path) -> bool:
    return any(_src_root(node) for node in ast.walk(parse(path)))


def test_no_source_module_derives_a_checkout_root_from_home_src() -> None:
    modules = source_modules()
    assert_floor(len(modules), SOURCE_FLOOR, 'kit source')
    assert [rel(path) for path in modules if _derives_src_root(path)] == []


def test_a_planted_home_src_root_is_found(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: each spelling is found, and the forge-home derivation passes."""
    for name, text in (
        ('call', "from pathlib import Path\nroot = Path.home() / 'src'\n"),
        ('tilde', "ROOT = '~/src/dev-lab'\n"),
        ('backslash', "ROOT = r'~\\src'\n"),
    ):
        planted = tmp_path / f'planted_{name}.py'
        planted.write_text(text, encoding='utf-8')
        assert _derives_src_root(planted), name
    clean = tmp_path / 'clean.py'
    clean.write_text("from pathlib import Path\nroot = Path.home() / '.local' / 'share'\n", encoding='utf-8')
    assert not _derives_src_root(clean)
