"""COMPONENTS: a product mounts each engine once, declared in ``[tool.lab_commons.components]``.

C1 is the table's schema and loader: every key is known, every required key is present, and a
refusal names the row and the key. C2 is the derive-and-check over ``.gitmodules``,
``[tool.uv.sources]``, Cargo path dependencies and the gitlinks themselves; each arm is driven with
PLANTED texts, the clean one first, so a check that read nothing could not pass.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import run_git

from dev_lab.dev.components import (
    Component,
    ComponentRefused,
    components_of,
    drift,
    drift_at,
    gitmodules_text,
    main,
    submodules,
)
from lab_commons.hpc.declared import KNOWN_TABLES

_ROW = """
[tool.lab_commons.components.numerics-lab]
url = "https://forge.example/lab/numerics-lab.git"
branch = "main"
parts = ["base", "linux"]
package = "numerics-lab"
crates = { numerics = "crates/numerics" }
"""


def test_a_declared_row_loads_with_its_path_derived_from_its_name() -> None:
    (row,) = components_of(_ROW)
    assert row == Component(
        name='numerics-lab',
        url='https://forge.example/lab/numerics-lab.git',
        branch='main',
        parts=('base', 'linux'),
        package='numerics-lab',
        crates={'numerics': 'crates/numerics'},
    )
    assert row.path == 'components/numerics-lab'


def test_no_table_is_no_components_and_the_table_is_one_the_kit_knows() -> None:
    assert components_of('[project]\nname = "x"\n') == ()
    assert 'components' in KNOWN_TABLES, 'an unknown table is refused by kit_tables before this reader runs'


def test_the_optional_keys_default_to_nothing() -> None:
    (row,) = components_of(
        '[tool.lab_commons.components.geo-lab]\nurl = "https://f/o/geo-lab.git"\nbranch = "main"\nparts = ["base"]\n'
    )
    assert (row.package, dict(row.crates)) == ('', {})


@pytest.mark.parametrize(
    ('text', 'refusal'),
    [
        (_ROW.replace('branch = "main"\n', ''), r'numerics-lab.*missing.*branch'),
        (_ROW + 'ref = "main"\n', r'numerics-lab.*unknown.*ref'),
        (_ROW + 'path = "components/numerics-lab"\n', r'numerics-lab.*unknown.*path.*derived'),
        (_ROW.replace('parts = ["base", "linux"]', 'parts = []'), r'numerics-lab.*parts.*at least one'),
        (_ROW.replace('parts = ["base", "linux"]', 'parts = "base"'), r'numerics-lab.*parts.*list'),
        (_ROW.replace('url = "https://forge.example/lab/numerics-lab.git"', 'url = ""'), r'numerics-lab.*url'),
        (_ROW.replace('crates = { numerics = "crates/numerics" }', 'crates = { numerics = "../x" }'), r'inside'),
        (_ROW.replace('numerics-lab]', 'numerics]'), r"'numerics'.*<x>-lab"),
        (_ROW.replace('numerics-lab]', 'lab-commons]'), r'lab-commons.*floating git dependency'),
        ('[tool.lab_commons]\ncomponents = ["numerics-lab"]\n', r'one table per engine'),
    ],
)
def test_a_row_the_schema_does_not_admit_is_refused_naming_the_row_and_the_key(text: str, refusal: str) -> None:
    with pytest.raises(ComponentRefused, match=refusal):
        components_of(text)


# --- C2: derive-and-check -------------------------------------------------------------------------

_SOURCES = '\n[tool.uv.sources]\nnumerics-lab = { path = "components/numerics-lab", editable = true }\n'
_CARGO = {
    'rust/Cargo.toml': '[workspace.dependencies]\nnumerics = { path = "../components/numerics-lab/crates/numerics" }\n'
}
_LINKS = frozenset({'components/numerics-lab'})


def _drift(planted: Mapping[str, Any] | None = None) -> tuple[str, ...]:
    """The drift of the clean mount with the *planted* inputs swapped in."""
    rows = components_of(_ROW)
    given = dict(planted or {})
    return drift(
        rows,
        gitmodules=given.get('gitmodules', gitmodules_text(rows)),
        pyproject=_ROW + given.get('sources', _SOURCES),
        cargo=given.get('cargo', _CARGO),
        gitlinks=given.get('gitlinks', _LINKS),
    )


def test_a_mount_derived_from_the_table_has_no_drift() -> None:
    """THE CLEAN ARM, read through every file: the planted reds below differ from it in one place each."""
    assert _drift() == ()
    assert submodules(gitmodules_text(components_of(_ROW))) == {
        'components/numerics-lab': {
            'path': 'components/numerics-lab',
            'url': 'https://forge.example/lab/numerics-lab.git',
            'branch': 'main',
        }
    }


def test_foreign_submodules_and_path_dependencies_outside_the_mount_are_not_policed() -> None:
    other = '[submodule "data"]\n\tpath = cases/data\n\turl = https://f/o/data.git\n'
    cargo = _CARGO | {'rust/crates/a/Cargo.toml': '[dependencies]\nb = { path = "../b" }\n'}
    assert _drift({'gitmodules': gitmodules_text(components_of(_ROW)) + other, 'cargo': cargo}) == ()


@pytest.mark.parametrize(
    ('planted', 'named'),
    [
        ({'gitmodules': ''}, r'\.gitmodules has no entry at components/numerics-lab'),
        ({'gitmodules': '[submodule "x"]\n\tpath = components/numerics-lab\n\turl = https://f/o/n.git\n'}, 'says'),
        ({'gitlinks': frozenset()}, 'no gitlink there'),
        ({'gitlinks': _LINKS | {'components/ai-lab'}}, 'components/ai-lab is a gitlink no component declares'),
        ({'sources': ''}, r'\[tool\.uv\.sources\] numerics-lab is None'),
        ({'sources': _SOURCES.replace('components/numerics-lab', '../numerics-lab')}, 'numerics-lab is'),
        ({'sources': _SOURCES + 'other = { path = "components/numerics-lab/py" }\n'}, 'other points into'),
        ({'cargo': {}}, 'declares crate numerics .* no Cargo.toml uses it'),
        ({'cargo': {'rust/Cargo.toml': '[dependencies]\nfoo = { path = "../components/numerics-lab/x" }\n'}}, 'foo'),
    ],
)
def test_each_drift_is_named(planted: dict[str, object], named: str) -> None:
    """THE PLANTED CONTROLS: one file moved off the table at a time, and the drift names that file."""
    problems = _drift(planted)
    assert any(re.search(named, problem) for problem in problems), problems


def test_the_checkout_reader_reads_the_index_gitmodules_and_cargo(tmp_path: Path) -> None:
    """``drift_at`` over a REAL git index holding a gitlink, so the reader is not trusted on its word."""
    run_git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text(_ROW + _SOURCES, encoding='utf-8')
    (tmp_path / '.gitmodules').write_text(gitmodules_text(components_of(_ROW)), encoding='utf-8')
    (tmp_path / 'rust').mkdir()
    (tmp_path / 'rust' / 'Cargo.toml').write_text(_CARGO['rust/Cargo.toml'], encoding='utf-8')
    run_git(tmp_path, 'add', 'pyproject.toml', '.gitmodules', 'rust/Cargo.toml')
    assert drift_at(tmp_path) == ('components/numerics-lab is declared and the index holds no gitlink there',)
    run_git(tmp_path, 'update-index', '--add', '--cacheinfo', f'160000,{"a" * 40},components/numerics-lab')
    assert drift_at(tmp_path) == ()
    assert main(['--root', str(tmp_path)]) == 0
