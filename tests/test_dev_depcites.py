"""OWNER-DAG over the declaration: a name a reason cites must be granted by a row (packages, stdlib, crates)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev import depcites, deptable

if TYPE_CHECKING:
    from pathlib import Path

HONEST = """
[python.owners]
runtime = []
[python.native]
kernel = "runtime"
[python.packages]
numerics_lab = { owners = ["src/pkg/runtime"], reason = "sampling drivers" }
"lab_commons.temp" = { owners = ["*"], reason = "the family temp tree" }
[python.stdlib]
tempfile = { owners = [], reason = "lab_commons.temp; see manifest.toml" }
[rust.crates]
kernel = []
[rust.external]
numerics = { crates = ["kernel"], reason = "the solver; `faer` stays out" }
faer = { crates = [], reason = "linear algebra is `numerics`'s" }
[rust.std]
"std::env" = { crates = [], reason = "explicit configuration; never `std::env::var`" }
"""


def _decl(tmp_path: Path, text: str) -> deptable.Declared:
    (tmp_path / deptable.FILE).write_text(text, encoding='utf-8')
    decl = deptable.load(tmp_path)
    assert decl is not None
    return decl


def test_cited_reads_backticks_and_dotted_names_with_a_known_top() -> None:
    tops = frozenset({'lab_commons'})
    assert depcites.cited('use lab_commons.temp, not manifest.toml or e.g. foo.bar', tops) == ['lab_commons.temp']
    assert depcites.cited('`numerics_lab` and `std::fs` and importlib.resources', tops) == [
        'numerics_lab',
        'std::fs',
        'importlib.resources',
    ]


def test_an_honest_declaration_cites_only_granted_names(tmp_path: Path) -> None:
    """THE PLANTED CONTROL: every citation above has its row, so nothing is refused."""
    assert depcites.problems(_decl(tmp_path, HONEST)) == []


def test_a_cited_package_crate_or_std_path_without_a_row_is_refused(tmp_path: Path) -> None:
    planted = (
        HONEST.replace('numerics_lab = ', 'other_lab = ')
        .replace('reason = "sampling drivers"', 'reason = "drivers come from `numerics_lab`"')
        .replace('faer = { crates = [], reason = "linear algebra is `numerics`\'s" }\n', '')
        .replace('never `std::env::var`', 'never `std::fs`')
    )
    assert depcites.problems(_decl(tmp_path, planted)) == [
        (
            'dependencies.toml [python.packages] other_lab cites numerics_lab in its reason, which no '
            '[python.packages] row grants'
        ),
        (
            'dependencies.toml [rust.external] numerics cites faer in its reason, which no [rust.external] or '
            '[rust.crates] row grants'
        ),
        'dependencies.toml [rust.std] std::env cites std::fs in its reason, which no [rust.std] row grants',
    ]


def test_a_native_crate_that_is_no_crate_row_is_refused(tmp_path: Path) -> None:
    planted = HONEST.replace('[rust.crates]\nkernel = []', '[rust.crates]\nother = []').replace(
        'crates = ["kernel"]', 'crates = ["other"]'
    )
    assert depcites.problems(_decl(tmp_path, planted)) == [
        'dependencies.toml [python.native] kernel names a crate no [rust.crates] row declares'
    ]
