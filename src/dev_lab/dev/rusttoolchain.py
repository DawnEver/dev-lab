"""THE FAMILY RUST TOOLCHAIN (user ruling 2026-11-24): ONE fact, rendered into every repo that declares Rust.

A repo that commits Rust must carry a root ``rust-toolchain.toml`` pinning one exact version
(:func:`dev_lab.dev.lockcheck.toolchain_problems`). Until now each repo wrote its own; now the version and the
shared components live HERE (:data:`CHANNEL`, :data:`COMPONENTS`) and the file is a render -- a hand edit reds
(:func:`drift`). The repo's delta is ``[tool.dev_lab.rust]`` in its ``pyproject.toml``: ``components`` and
``targets`` (lists appended to the base's); any other key is refused by name.

``python -m dev_lab.dev.rusttoolchain render|check [--repo PATH]``
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any, Final

from lab_commons.log import emit

from dev_lab.dev.family import declared_table
from dev_lab.dev.lockcheck import TOOLCHAIN

__all__ = ['CHANNEL', 'COMPONENTS', 'DELTA_TABLE', 'RENDER_COMMAND', 'STAMP', 'drift', 'main', 'render', 'write']

#: The one exact toolchain every family Rust tree builds with (a version, never a channel name).
CHANNEL: Final = '1.100.0'
#: The components every family Rust tree needs: the formatter and the linter the gate runs.
COMPONENTS: Final[tuple[str, ...]] = ('clippy', 'rustfmt')
#: The repo's delta: ``[tool.dev_lab.rust]``.
DELTA_TABLE: Final = 'rust'
_DELTA_KEYS: Final = frozenset({'components', 'targets'})
STAMP: Final = '# Rendered by dev_lab.dev.rusttoolchain from the family toolchain; hand edits RED.'
RENDER_COMMAND: Final = 'python -m dev_lab.dev.rusttoolchain render'


def _delta(root: Path) -> dict[str, Any]:
    path = root / 'pyproject.toml'
    data = tomllib.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    delta = dict(declared_table(data, DELTA_TABLE, {}))
    if unknown := sorted(set(delta) - _DELTA_KEYS):
        msg = f'[tool.dev_lab.{DELTA_TABLE}] declares {unknown}; a delta holds only {sorted(_DELTA_KEYS)}'
        raise ValueError(msg)
    if restated := sorted(set(delta.get('components', [])) & set(COMPONENTS)):
        msg = f'[tool.dev_lab.{DELTA_TABLE}] components restates the family base {restated}; delete them'
        raise ValueError(msg)
    return delta


def _array(values: list[str]) -> str:
    return '[' + ', '.join(f'"{value}"' for value in values) + ']'


def render(root: Path) -> str:
    """The file's bytes: the stamp, then the family channel and components, then the repo's delta."""
    delta = _delta(root)
    lines = [
        STAMP,
        '[toolchain]',
        f'channel = "{CHANNEL}"',
        f'components = {_array([*COMPONENTS, *delta.get("components", [])])}',
    ]
    if delta.get('targets'):
        lines.append(f'targets = {_array(list(delta["targets"]))}')
    return '\n'.join(lines) + '\n'


def drift(root: Path) -> str | None:
    """Why *root*'s toolchain file is not the render, else ``None``."""
    path = root / TOOLCHAIN
    if not path.is_file():
        return f'{TOOLCHAIN}: absent -- {RENDER_COMMAND}'
    if path.read_text(encoding='utf-8') != render(root):
        return f'{TOOLCHAIN}: differs from the family toolchain (hand-edited, or the family moved) -- {RENDER_COMMAND}'
    return None


def write(root: Path) -> str:
    """Render *root*'s toolchain file; one status line."""
    path = root / TOOLCHAIN
    text = render(root)
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return f'{TOOLCHAIN}: current'
    path.write_text(text, encoding='utf-8', newline='\n')
    return f'{TOOLCHAIN}: rendered'


def main(argv: list[str] | None = None) -> int:
    """CLI: ``render`` writes, ``check`` exits 1 naming the drift."""
    parser = argparse.ArgumentParser(description='Render the family rust-toolchain.toml into a repo.')
    parser.add_argument('action', choices=('render', 'check'))
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.repo.resolve()
    if args.action == 'check':
        problem = drift(root)
        emit(f'[rusttoolchain] {problem or f"{TOOLCHAIN}: current"}')
        return 1 if problem else 0
    emit(f'[rusttoolchain] {write(root)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
