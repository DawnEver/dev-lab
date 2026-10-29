"""A row is a part qualified by one OS: :mod:`dev_lab.dev.partrows`."""

from __future__ import annotations

from dev_lab.dev import partrows


def test_a_row_names_one_os_and_its_part() -> None:
    assert (partrows.row_part('femm+windows'), partrows.row_system('femm+windows')) == ('femm+windows', '')
    assert (partrows.row_part('base@macos'), partrows.row_system('base@macos')) == ('base', 'macos')
    assert partrows.is_row('base@windows')
    assert partrows.is_row('base')
    assert not partrows.is_row('base@femm'), 'only an OS qualifies a row'


def test_this_platform_is_an_os_a_row_may_name() -> None:
    assert partrows.is_row(f'base@{partrows.this_platform()}')
