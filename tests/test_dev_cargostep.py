"""CARGO RUNS NATIVELY BESIDE PYTEST (T8, 2026-11-24): its own step, its own result, never a pytest wrapper."""

from __future__ import annotations

import io
from pathlib import Path

from dev_lab.dev import cargostep


def _plant(root: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding='utf-8')
    return sorted(files)


def test_the_workspaces_are_the_manifests_declaring_one_and_a_root_package(tmp_path: Path) -> None:
    tracked = _plant(
        tmp_path,
        {
            'rust/Cargo.toml': '[workspace]\nmembers = ["crates/a"]\n',
            'rust/crates/a/Cargo.toml': '[package]\nname = "a"\n',
            'tests/planted_failing_crate/Cargo.toml': '[package]\nname = "planted"\n',
            'pyproject.toml': '',
        },
    )
    assert cargostep.workspaces(tmp_path, tracked) == ('rust/Cargo.toml',)
    root_package = _plant(tmp_path / 'other', {'Cargo.toml': '[package]\nname = "solo"\n'})
    assert cargostep.workspaces(tmp_path / 'other', root_package) == ('Cargo.toml',)


def test_a_repo_without_rust_has_no_cargo_step(tmp_path: Path) -> None:
    assert cargostep.workspaces(tmp_path, _plant(tmp_path, {'pyproject.toml': ''})) == ()


def test_a_failing_cargo_run_is_its_own_named_red_and_a_passing_one_its_own_green(tmp_path: Path) -> None:
    """PLANTED CONTROL, both sides, through the real step with the process runner planted."""
    argv_seen: list[list[str]] = []

    def run(code: int):  # noqa: ANN202 -- a planted runner
        def tee(argv: list[str], *, cwd: Path, handle: io.StringIO) -> int:
            del cwd, handle
            argv_seen.append(argv)
            return code

        return tee

    green = cargostep.step(tmp_path, 'rust/Cargo.toml', handle=io.StringIO(), tee=run(0), cargo='cargo')
    red = cargostep.step(tmp_path, 'rust/Cargo.toml', handle=io.StringIO(), tee=run(101), cargo='cargo')
    assert green.name == red.name == 'cargo test rust/Cargo.toml'
    assert (green.reported, green.failures) == ((green.name,), ())
    assert (red.reported, red.failures) == ((red.name,), (red.name,))
    assert argv_seen[0] == ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--workspace', '--locked']


def test_no_cargo_on_the_host_is_inconclusive_naming_the_door(tmp_path: Path) -> None:
    report = cargostep.step(tmp_path, 'rust/Cargo.toml', handle=io.StringIO(), tee=None, cargo=None)
    assert report.reported == ()
    assert any('cargo' in line and 'rust-toolchain' in line for line in report.truncated)
