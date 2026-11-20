"""The in-process row runner reports what ``python -m`` would, even when a row closes its stdout (#677)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from dev_lab.dev.githooks import inprocess

if TYPE_CHECKING:
    from pathlib import Path


def _module(tmp_path: Path, name: str, body: str) -> str:
    (tmp_path / f'{name}.py').write_text(body, encoding='utf-8')
    return name


def test_a_row_that_closes_stdout_exits_with_its_own_code_and_its_output_is_reported(tmp_path: Path) -> None:
    name = _module(
        tmp_path, 'closes_stdout', "import sys\nprint('said before closing')\nsys.stdout.close()\nsys.exit(3)\n"
    )
    stdout = sys.stdout
    code, out = inprocess.run(name, [], tmp_path, None, {})
    assert code == 3
    assert 'said before closing' in out
    assert sys.stdout is stdout  # the runner's own stream is restored, never left closed


def test_an_ordinary_row_is_unchanged(tmp_path: Path) -> None:
    """Planted control: a row that leaves stdout open reports its output and exit code as before."""
    name = _module(tmp_path, 'plain_row', "print('plain output')\n")
    code, out = inprocess.run(name, [], tmp_path, None, {})
    assert code == 0
    assert 'plain output' in out
