"""CARGO RUNS NATIVELY BESIDE PYTEST (T8, 2026-11-24): its own step, its own result, never a pytest wrapper."""

from __future__ import annotations

import io
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import cargostep, localpart
from dev_lab.dev.platformparts import part_context
from dev_lab.dev.producer import PRODUCING_VAR, ProducerExit, producing


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

    def run(code: int) -> Callable[..., int]:
        def tee(argv: list[str], *, cwd: Path, handle: io.StringIO) -> int:
            del cwd, handle
            argv_seen.append(argv)
            return code

        return tee

    green = cargostep.step(tmp_path, 'rust/Cargo.toml', 'test', handle=io.StringIO(), tee=run(0), cargo='cargo')
    red = cargostep.step(tmp_path, 'rust/Cargo.toml', 'test', handle=io.StringIO(), tee=run(101), cargo='cargo')
    assert green.name == red.name == 'cargo test rust/Cargo.toml'
    assert (green.reported, green.failures) == ((green.name,), ())
    assert (red.reported, red.failures) == ((red.name,), (red.name,))
    assert argv_seen[0] == ['cargo', 'test', '--manifest-path', 'rust/Cargo.toml', '--workspace', '--locked']


def test_rustfmt_and_clippy_are_steps_of_their_own_beside_cargo_test() -> None:
    """dev-lab#1033: formatting and lint drift is a named red, never a later child's re-format."""
    assert cargostep.COMMANDS == ('fmt', 'clippy', 'doc', 'test')
    assert cargostep.argv('cargo', 'Cargo.toml', 'fmt') == [
        'cargo', 'fmt', '--manifest-path', 'Cargo.toml', '--all', '--', '--check'
    ]  # fmt: skip
    assert cargostep.argv('cargo', 'Cargo.toml', 'clippy') == [
        'cargo', 'clippy', '--manifest-path', 'Cargo.toml', '--workspace', '--all-targets', '--locked',
        '--', '-D', 'warnings',
    ]  # fmt: skip


def test_rustdoc_is_a_step_of_its_own_denying_warnings() -> None:
    """dev-lab#1082: a broken intra-doc link or bare URL is a named red, ``cargo doc <manifest>``."""
    assert cargostep.node('Cargo.toml', 'doc') == 'cargo doc Cargo.toml'
    assert cargostep.argv('cargo', 'Cargo.toml', 'doc') == [
        'cargo', 'doc', '--manifest-path', 'Cargo.toml', '--workspace', '--no-deps', '--locked',
        '--config', 'build.rustdocflags=["-D", "warnings"]',
    ]  # fmt: skip


def test_no_cargo_on_the_host_is_inconclusive_naming_the_door(tmp_path: Path) -> None:
    report = cargostep.step(tmp_path, 'rust/Cargo.toml', 'test', handle=io.StringIO(), tee=None, cargo=None)
    assert report.reported == ()
    assert any('cargo' in line and 'rust-toolchain' in line for line in report.truncated)


def _repo(tmp_path: Path) -> Path:
    git = shutil.which('git') or 'git'
    _plant(tmp_path, {'rust/Cargo.toml': '[workspace]\nmembers = []\n', 'pyproject.toml': ''})
    for args in (['init', '-q'], ['add', '-A'], ['-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'x']):
        subprocess.run([git, '-C', str(tmp_path), *args], check=True, capture_output=True, timeout=60)
    return tmp_path


def _producing(monkeypatch: pytest.MonkeyPatch, posted: list[dict[str, Any]]) -> None:
    monkeypatch.setenv(PRODUCING_VAR, producing(part_context(cargostep.PART), 'a' * 40)[PRODUCING_VAR])
    monkeypatch.setattr(localpart, 'post_local', lambda _root, record, _dir: posted.append(record) or 'posted')
    monkeypatch.setattr(cargostep, 'record_directory', lambda root, _sha: root)


@pytest.mark.parametrize(
    ('code', 'status', 'exit_code'), [(0, 'ok', ProducerExit.PASS), (101, 'rejected', ProducerExit.FAIL)]
)
def test_the_cargo_part_posts_one_cell_per_workspace_as_tests_cargo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, status: str, exit_code: int
) -> None:
    """PLANTED CONTROL, both sides: the part is red exactly when cargo is, and it is tests/cargo's own record."""
    posted: list[dict[str, Any]] = []
    _producing(monkeypatch, posted)
    doc_only = cargostep.produce(
        _repo(tmp_path / 'doc'), run=lambda argv: code if argv[1] == 'doc' else 0, cargo='cargo'
    )
    assert doc_only == exit_code, 'a red rustdoc alone reds the part'
    assert posted.pop()['cells']['cargo doc rust/Cargo.toml']['status'] == status
    fmt_only = cargostep.produce(
        _repo(tmp_path / 'fmt'), run=lambda argv: code if argv[1] == 'fmt' else 0, cargo='cargo'
    )
    assert fmt_only == exit_code, 'an unformatted file alone reds the part'
    (record,) = posted
    assert record['platform'] == 'cargo'
    assert record['cells']['cargo fmt rust/Cargo.toml']['status'] == status
    assert record['cells']['cargo clippy rust/Cargo.toml']['status'] == 'ok'
    assert record['cells']['cargo doc rust/Cargo.toml']['status'] == 'ok'
    assert record['cells']['cargo test rust/Cargo.toml']['status'] == 'ok'


def test_the_cargo_part_is_refused_outside_its_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PRODUCING_VAR, raising=False)
    assert cargostep.produce(_repo(tmp_path), run=lambda _argv: 0, cargo='cargo') == ProducerExit.USAGE


def test_a_pytest_part_hands_each_workspace_to_the_cargo_part(tmp_path: Path) -> None:
    """How the forge DISCOVERS tests/cargo: the base part's record hands it the workspace cells."""
    tracked = _plant(tmp_path, {'rust/Cargo.toml': '[workspace]\n'})
    assert cargostep.handed(tmp_path, tracked) == {
        f'cargo {command} rust/Cargo.toml': 'cargo' for command in ('fmt', 'clippy', 'doc', 'test')
    }
    assert cargostep.handed(tmp_path, []) == {}
