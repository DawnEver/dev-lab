"""The toolchain diagnosis names each gap the target checkout needs, and nothing it does not."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dev_lab.dev.toolchain import diagnose, probe_linker

if TYPE_CHECKING:
    from pathlib import Path


def _checkout(root: Path, *, rust: bool) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / 'pyproject.toml').write_text('[project]\nname = "x"\nrequires-python = ">=3.13"\n', encoding='utf-8')
    if rust:
        (root / 'rust').mkdir()
        (root / 'rust' / 'Cargo.toml').write_text('[workspace]\n', encoding='utf-8')
    return root


def test_a_bare_host_is_told_every_gap_at_once(tmp_path: Path) -> None:
    root = _checkout(tmp_path / 'c', rust=True)
    root_home = tmp_path / 'home'
    gaps = diagnose(root, which=lambda _t: None, home=root_home, python_found=lambda _uv, _s: False)
    assert [gap.tool for gap in gaps] == ['git', 'uv', 'cargo']


def test_the_python_asked_for_is_the_targets_requires_python(tmp_path: Path) -> None:
    root = _checkout(tmp_path, rust=False)
    asked: list[str] = []
    gaps = diagnose(root, which=lambda t: f'/bin/{t}', python_found=lambda _uv, spec: asked.append(spec) or False)
    assert asked == ['>=3.13']
    assert [gap.tool for gap in gaps] == ['python >=3.13']


def test_a_complete_host_and_a_checkout_without_rust_have_no_gap(tmp_path: Path) -> None:
    """Planted control: the diagnosis must be able to say nothing is missing."""
    root = _checkout(tmp_path, rust=False)
    assert diagnose(root, which=lambda _t: None if _t == 'cargo' else '/bin/x', python_found=lambda *_: True) == []


def test_rustups_own_bin_counts_as_cargo(tmp_path: Path) -> None:
    root = _checkout(tmp_path / 'c', rust=True)
    home = tmp_path / 'home'
    (home / '.cargo' / 'bin').mkdir(parents=True)
    for name in ('cargo', 'cargo.exe'):
        (home / '.cargo' / 'bin' / name).write_text('', encoding='utf-8')
    found = diagnose(root, which=lambda t: None if t == 'cargo' else '/bin/x', home=home, python_found=lambda *_: True)
    assert found == []


def test_the_linker_probe_carries_the_pin_and_names_the_failure(tmp_path: Path) -> None:
    root = _checkout(tmp_path / 'c', rust=True)
    (root / 'rust-toolchain.toml').write_text('[toolchain]\nchannel = "1.90"\n', encoding='utf-8')
    work = tmp_path / 'work'
    seen: list[bool] = []

    def failing(_argv: list[str]) -> tuple[int, str]:
        seen.append((work / 'linker_probe' / 'rust-toolchain.toml').is_file())
        return 1, 'error: linker `link.exe` not found\n'

    gap = probe_linker(root, 'cargo', run=failing, work=work)
    assert seen == [True]
    assert gap is not None
    assert 'link.exe' in gap.why
    assert probe_linker(root, 'cargo', run=lambda _argv: (0, ''), work=work) is None
