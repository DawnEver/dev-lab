"""MEASURE-BEFORE-PORTING: a head adding a crate is refused until one of its commits carries a measured number."""

from __future__ import annotations

from pathlib import Path

from _forge_fake import git_out

from dev_lab.dev.portmeasure import TRAILER, added_crates, measured, unmeasured


def _git(root: Path, *args: str) -> str:
    return git_out(root, *args)


def _commit(root: Path, name: str, message: str) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(name, encoding='utf-8')
    _git(root, 'add', name)
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-m', message)
    return _git(root, 'rev-parse', 'HEAD')


def _repo(tmp_path: Path) -> tuple[Path, str]:
    _git(tmp_path, 'init', '-q')
    return tmp_path, _commit(tmp_path, 'Cargo.toml', 'chore: the workspace')


def test_only_an_added_manifest_is_a_new_crate(tmp_path: Path) -> None:
    """PLANTED CONTROL: an edited workspace manifest and a plain file add no crate."""
    root, base = _repo(tmp_path)
    (root / 'Cargo.toml').write_text('[workspace]\n', encoding='utf-8')
    _git(root, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '--no-verify', '-am', 'chore: edit')
    head = _commit(root, 'src/x.py', 'feat: x')
    assert added_crates(root, base, head) == ()
    head = _commit(root, 'crates/fast/Cargo.toml', 'feat: fast')
    assert added_crates(root, base, head) == ('crates/fast/Cargo.toml',)


def test_a_record_must_name_a_number() -> None:
    assert not measured([])
    assert not measured(['it is faster'])
    assert measured(['python 18.7 us -> rust 9.08 us, 2.1x'])


def test_a_crate_without_a_measured_trailer_is_refused_and_with_one_is_admitted(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    head = _commit(root, 'crates/fast/Cargo.toml', f'feat: fast\n\n{TRAILER}: faster, surely')
    refused = unmeasured(root, base, head)
    assert refused is not None
    assert refused.startswith('MEASURE-BEFORE-PORTING')
    assert 'crates/fast/Cargo.toml' in refused
    head = _commit(root, 'crates/fast/src/lib.rs', f'perf: fast\n\n{TRAILER}: python 18.7 us -> rust 9.08 us, 2.1x')
    assert unmeasured(root, base, head) is None


def test_a_head_adding_no_crate_needs_no_record(tmp_path: Path) -> None:
    root, base = _repo(tmp_path)
    assert unmeasured(root, base, _commit(root, 'src/x.py', 'feat: x')) is None
