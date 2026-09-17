"""The dated-log layout, driven against a REAL filesystem rather than against its own string maths.

Every arm here writes or refuses on a real temporary tree, because the whole subject is a directory
that must exist afterwards: an assertion about the returned ``Path`` alone would pass against a
version that never called ``mkdir``, which is the one thing the caller depends on.

THE NO-DEFAULT ARM IS THE POINT OF THE MIGRATION and is checked by SIGNATURE rather than by calling:
a call omitting ``base`` is a ``TypeError`` at the call site, so a test that merely expects an
exception cannot tell "refused" from "misspelled". Reading the signature says WHICH parameters are
required, which is the property the module docstring claims.
"""

from __future__ import annotations

import datetime
import inspect
from pathlib import Path

import pytest

from lab_commons.dev.datedlog import date_parts, dated_log


def test_the_three_parts_are_todays_local_date_two_digits_each() -> None:
    """A floor under the format: two digits each, and the same day the box thinks it is."""
    yy, mm, dd = date_parts()
    today = datetime.datetime.now().astimezone()
    assert (yy, mm, dd) == (today.strftime('%y'), today.strftime('%m'), today.strftime('%d'))
    assert all(len(part) == 2 and part.isdigit() for part in (yy, mm, dd))


def test_the_directory_is_created_and_the_file_is_not(tmp_path: Path) -> None:
    """The parent EXISTS on return; the file does not, because writing it is the caller's."""
    got = dated_log(tmp_path, 'gate.log', base='output/logs', kind='gate')
    assert got.parent.is_dir()
    assert not got.exists()
    assert got.relative_to(tmp_path).as_posix() == f'output/logs/{"/".join(date_parts())}/gate/gate.log'


def test_a_multi_segment_base_becomes_real_directories(tmp_path: Path) -> None:
    """A base is a LOCATION, so its separators are segments and never one oddly-named directory."""
    got = dated_log(tmp_path, 'x.log', base='a/b/c', kind='k')
    assert (tmp_path / 'a' / 'b' / 'c').is_dir()
    assert got.parent.parent.name == 'c' or 'a/b/c' in got.as_posix()


def test_two_kinds_on_one_day_are_two_directories(tmp_path: Path) -> None:
    """The kind is a real partition beneath the date, not a filename prefix."""
    one = dated_log(tmp_path, 'a.log', base='output/logs', kind='gate')
    two = dated_log(tmp_path, 'a.log', base='output/logs', kind='durations')
    assert one != two
    assert one.parent.parent == two.parent.parent


def test_calling_twice_is_idempotent_and_keeps_what_is_already_there(tmp_path: Path) -> None:
    """``exist_ok`` is load-bearing: a second harness on the same day must not wipe the first's."""
    first = dated_log(tmp_path, 'a.log', base='output/logs', kind='gate')
    first.write_text('evidence', encoding='utf-8')
    second = dated_log(tmp_path, 'b.log', base='output/logs', kind='gate')
    assert second.parent == first.parent
    assert first.read_text(encoding='utf-8') == 'evidence'


@pytest.mark.parametrize(
    'name',
    [
        '',
        '.',
        '..',
        'sub/gate.log',
        r'sub\gate.log',
        'C:/var/gate.log',
        '/var/gate.log',
    ],
)
def test_a_name_that_is_a_path_is_refused_rather_than_normalised(tmp_path: Path, name: str) -> None:
    """THE PLANTED CONTROL IN THE REFUSING DIRECTION -- including the two hatches that were removed.

    ``C:/var/gate.log`` is the absolute spelling the old ``is_absolute()`` hatch waved through, and
    ``sub/gate.log`` is the relative one the ``'logs' in parts`` hatch could reach. Both must refuse,
    and nothing may be written anywhere while they do.
    """
    with pytest.raises(ValueError, match='NAME, not a path'):
        dated_log(tmp_path, name, base='output/logs', kind='gate')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('base', ['', '/var/log', 'C:/logs', '../elsewhere', 'a/../../b'])
def test_a_base_that_escapes_the_root_is_refused(tmp_path: Path, base: str) -> None:
    """A base that can ESCAPE makes the ``root/`` in the return value a lie, so it never gets that far.

    ``/var/log`` is here because it is the arm that caught the first draft: ``WindowsPath`` reports
    it as relative, so a guard asking only the running platform lets a POSIX-absolute base through
    on the box where it does no harm and escapes on the box where it does.
    """
    with pytest.raises(ValueError, match='RELATIVE location'):
        dated_log(tmp_path, 'gate.log', base=base, kind='gate')
    assert list(tmp_path.iterdir()) == []


def test_a_plain_name_is_accepted_so_the_refusal_arms_are_not_vacuous(tmp_path: Path) -> None:
    """THE CONTROL IN THE OTHER DIRECTION: the guard above can still say yes."""
    assert dated_log(tmp_path, 'gate.log', base='output/logs', kind='gate').name == 'gate.log'


def test_base_and_kind_are_REQUIRED_KEYWORDS_with_no_default() -> None:
    """The migration's whole point, read off the SIGNATURE.

    A default for ``base`` would hand any other repo in this family motronics' 2026-09-03 directive
    while reading as a shared convention -- and this package's own verify log lives at ``.verify/``,
    so the disagreement is inside one tree rather than hypothetical.
    """
    parameters = inspect.signature(dated_log).parameters
    for required in ('base', 'kind'):
        assert parameters[required].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[required].default is inspect.Parameter.empty
