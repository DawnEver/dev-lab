"""Controls for :mod:`dev_lab.dev.famtests.testleaks`: each leak shape is named by line, each owned shape is not."""

from __future__ import annotations

import pytest

from dev_lab.dev.famtests.testleaks import leaks

#: PLANTED: every line here leaks, and the reader must name each one.
_LEAKING = (
    'import tempfile\n'
    'tempfile.mkdtemp()\n'
    'mkstemp(suffix=".x")\n'
    'tempfile.NamedTemporaryFile(delete=False)\n'
    'Path(tempfile.gettempdir()) / "x"\n'
    "Path('/tmp/x').mkdir()\n"
    "Path('/var/tmp')\n"
    "root = 'C:\\\\'\n"
    "root = 'D:/'\n"
)

#: The control beside it: owned or inert shapes, none of which the reader may name.
_OWNED = (
    '"""A docstring naming /tmp is prose."""\n'
    'import tempfile\n'
    'with tempfile.TemporaryDirectory() as t:\n'
    '    pass\n'
    'tempfile.NamedTemporaryFile()\n'
    "cmd = 'cd /r/src/repos/dev-lab'\n"
    "label = 'c:'\n"
    "PureWindowsPath('C:/', 'Users')\n"
    "Path('/tmpfoo')\n"
)


def test_every_planted_leak_is_named_by_its_line() -> None:
    assert leaks(_LEAKING) == (2, 3, 4, 5, 6, 7, 8, 9)


def test_no_owned_or_inert_shape_is_named() -> None:
    assert leaks(_OWNED) == ()


#: Assembled, so this file holds no host-root literal of its own for the row to name.
_ROOTS = [f'/{tail}' for tail in ('tmp', 'tmp/a/b', 'var/tmp/lab')] + ['C:' + chr(92), 'z:' + '/']


@pytest.mark.parametrize('literal', _ROOTS)
def test_a_host_root_literal_is_named(literal: str) -> None:
    assert leaks(f'x = {literal!r}\n') == (1,)
