"""COMPONENTS: a product mounts each engine once, declared in ``[tool.lab_commons.components]``.

C1 is the table's schema and loader: every key is known, every required key is present, and a
refusal names the row and the key. C2 is the derive-and-check over ``.gitmodules``,
``[tool.uv.sources]``, Cargo path dependencies and the gitlinks themselves; each arm is driven with
PLANTED texts, the clean one first, so a check that read nothing could not pass.
"""

from __future__ import annotations

import pytest

from lab_commons.dev.components import Component, ComponentRefused, components_of
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
        '[tool.lab_commons.components.wdg-lab]\nurl = "https://f/o/wdg-lab.git"\nbranch = "main"\nparts = ["base"]\n'
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
