"""One need vocabulary: a test's markers name its resources, and its part is its need-set."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest
from lab_commons.hpc.declared import RetiredTable
from lab_commons.hpc.needsets import (
    BASE,
    Vocabulary,
    need_sets,
    needs_of,
    part_name,
    read_vocabulary,
    selecting,
)
from lab_commons.hpc.retired import RETIRED

PYPROJECT = """
[tool.lab_commons.tests]
resources = ["windows", "femm", "jmag"]
produce = ["-m", "dev_lab.dev.verify", "--part", "{part}"]
"""

_NAMES = ('femm', 'jmag', 'matlab', 'windows', 'linux', 'workstation')


def test_a_part_is_named_for_its_need_set_and_the_empty_set_is_base() -> None:
    assert part_name([]) == BASE == 'base'
    assert part_name(['windows', 'femm']) == 'femm+windows', 'sorted: one need-set, one name'
    assert part_name(['jmag', 'jmag']) == 'jmag'


@pytest.mark.parametrize('count', range(len(_NAMES) + 1))
def test_the_name_and_the_need_set_are_inverse(count: int) -> None:
    for names in itertools.combinations(_NAMES, count):
        assert needs_of(part_name(names)) == set(names)


@pytest.mark.parametrize('bad', ['windows+femm', 'femm+femm', 'base+femm', 'Femm', '', 'femm+'])
def test_a_name_that_is_not_one_need_set_is_refused(bad: str) -> None:
    with pytest.raises(ValueError, match='not a part name'):
        needs_of(bad)


def test_the_vocabulary_is_read_sorted_and_absent_is_none() -> None:
    assert read_vocabulary(PYPROJECT) == Vocabulary(('femm', 'jmag', 'windows'))
    assert read_vocabulary('[project]\nname = "x"\n') == Vocabulary()


@pytest.mark.parametrize('value', ['"femm"', '["Femm"]', '["base"]', '["femm", "femm"]', '[1]'])
def test_a_malformed_vocabulary_is_refused_naming_the_table(value: str) -> None:
    with pytest.raises(ValueError, match=r'\[tool\.lab_commons\.tests\] resources'):
        read_vocabulary(f'[tool.lab_commons.tests]\nresources = {value}\n')


#: The part tables the need vocabulary replaced, read off the registry by their REPLACEMENT (their spellings
#: live there and nowhere else); the registry also holds the tables that moved to dev-lab (A3).
_RETIRED_TABLES = sorted(key for key, why in RETIRED.items() if '[tool.lab_commons.tests] resources' in why)


def test_the_old_part_tables_are_registered_retired() -> None:
    assert len(_RETIRED_TABLES) == 2, 'the OS axis and the capability axis'


@pytest.mark.parametrize('table', _RETIRED_TABLES)
def test_a_retired_table_is_refused_naming_its_replacement(table: str) -> None:
    with pytest.raises(RetiredTable, match=r'is retired: \[tool\.lab_commons\.tests\] resources'):
        read_vocabulary(f'{table}\nfemm = ["windows"]\n')


def test_a_part_selects_exactly_its_need_set() -> None:
    vocabulary = read_vocabulary(PYPROJECT)
    assert selecting(vocabulary, BASE) == 'not femm and not jmag and not windows'
    assert selecting(vocabulary, 'femm+windows') == 'femm and not jmag and windows'
    assert selecting(Vocabulary(), BASE) == '', 'nothing to tell apart: every test is base'
    with pytest.raises(ValueError, match="needs \\['matlab'\\]"):
        selecting(vocabulary, 'matlab')


def test_the_suite_is_partitioned_by_need_set() -> None:
    carrying = {'femm': {'t::f', 't::fw'}, 'jmag': set(), 'windows': {'t::w', 't::fw'}}
    parts = need_sets(['t::a', 't::f', 't::w', 't::fw'], carrying)
    assert parts == {'t::a': BASE, 't::f': 'femm', 't::w': 'windows', 't::fw': 'femm+windows'}


def test_a_declared_workstation_resource_is_scarce_and_this_repo_declares_none() -> None:
    """A consumer whose live-checkout tests share one host declares ONE scarce ``workstation`` resource.

    Read on a planted declaration (the family mechanism); dev-lab itself declares no resource (user ruling
    2026-11-05: every test runs on a hosted runner), pinned against its real pyproject.
    """
    planted = read_vocabulary('[tool.lab_commons.tests]\nresources = ["workstation"]\nscarce = ["workstation"]\n')
    assert planted == Vocabulary(('workstation',), scarce=('workstation',))
    assert selecting(planted, BASE) == 'not workstation'
    declared = (Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8')
    assert read_vocabulary(declared) == Vocabulary((), scarce=())
