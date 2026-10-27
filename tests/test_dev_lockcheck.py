"""PIN and FRESHNESS are the forge's alone (user rulings 2026-10-17, 2026-10-22, 2026-10-24).

The repo's own suite judges the checked-out commit's PIN on the forge (:mod:`dev_lab.dev.famtests.lockpin`): it
commits ``uv.lock`` and holds nothing below the newest unreasoned. No pre-push row reads the lock.
The staleness reading :func:`stale` is the forge relock's (dev_lab.dev.relock), driven here on REAL planted
repositories with the REAL ``uv``, offline: the in-house git dependency is a local repository, and the PyPI-shaped
one a find-links directory of planted wheels. Each refusal has a planted control that passes.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from dev_lab.dev import forgeheadgate
from dev_lab.dev.famtests.lockpin import LockNotPinned, assert_the_lock_is_pinned
from dev_lab.dev.githooks.table import base_rows
from dev_lab.dev.lockcheck import (
    DOOR,
    REMEDY,
    UNRESOLVED,
    lock_problems,
    newest_stable,
    pin_stable,
    stale,
    unreasoned_holds,
)
from dev_lab.dev.relock import detached_worktree

_GIT = shutil.which('git') or 'git'
_UV = shutil.which('uv') or 'uv'


def _run(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        list(argv), cwd=cwd, check=False, capture_output=True, text=True, encoding='utf-8', timeout=300
    )  # fmt: skip
    assert done.returncode == 0, f'{argv} exited {done.returncode}: {done.stderr}'
    return done.stdout.strip()


def _git(root: Path, *argv: str) -> str:
    return _run(root, _GIT, '-c', 'user.name=t', '-c', 'user.email=t@t', *argv)


def _commit(root: Path, files: dict[str, str]) -> str:
    for name, text in files.items():
        (root / name).write_text(text, encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '--allow-empty', '-m', 'c')
    return _git(root, 'rev-parse', 'HEAD')


def _wheel(index: Path, version: str) -> None:
    info = f'dep-{version}.dist-info'
    with zipfile.ZipFile(index / f'dep-{version}-py3-none-any.whl', 'w') as wheel:
        wheel.writestr('dep/__init__.py', '')
        wheel.writestr(f'{info}/METADATA', f'Metadata-Version: 2.1\nName: dep\nVersion: {version}\n')
        wheel.writestr(f'{info}/WHEEL', 'Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        wheel.writestr(f'{info}/RECORD', '')


def _manifest(kit: Path, index: Path, dep: str) -> str:
    return f"""[project]
name = "planted"
version = "0"
requires-python = ">=3.12"
dependencies = [
    "kit @ git+{kit.as_uri()}",
    {dep}
]

[tool.uv]
no-index = true
find-links = ["{index.as_posix()}"]
"""


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, Path]:
    """``(consumer, kit, index)``: a consumer of an in-house git ``kit`` and a PyPI-shaped ``dep`` (1.0 only)."""
    monkeypatch.setenv('UV_CACHE_DIR', str(tmp_path / 'uv-cache'))
    monkeypatch.setenv('UV_PYTHON', sys.executable)
    kit, index, root = tmp_path / 'kit', tmp_path / 'index', tmp_path / 'consumer'
    for path in (kit, index, root):
        path.mkdir()
    _git(kit, 'init', '-q', '-b', 'main')
    _commit(kit, {'pyproject.toml': '[project]\nname = "kit"\nversion = "1.0"\n'})
    _wheel(index, '1.0')
    _git(root, 'init', '-q', '-b', 'main')
    return root, kit, index


def _locked(root: Path, manifest: str, *, upgrade: bool = False) -> str:
    (root / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    _run(root, _UV, 'lock', *(['--upgrade'] if upgrade else []))
    return _commit(root, {})


def test_a_stale_in_house_pin_is_refused_and_the_newest_admitted(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: the kit moves after the lock pinned it -- refused naming it; `uv lock --upgrade` admits."""
    root, kit, index = world
    _locked(root, _manifest(kit, index, '"dep",'))
    assert stale(root) == (), 'CONTROL: a lock at the newest resolution is admitted'
    _commit(kit, {'README': 'moved'})
    (why,) = stale(root)
    assert why.startswith('uv.lock is not the newest resolution: Update kit'), why
    _locked(root, _manifest(kit, index, '"dep",'), upgrade=True)
    assert stale(root) == ()


def test_pypi_is_held_at_latest_unless_a_declared_range_says_why(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: dep 2.0 is published. Unheld -> refused; a reasoned `<2` -> admitted; an unreasoned one -> refused."""
    root, kit, index = world
    _locked(root, _manifest(kit, index, '"dep",'))
    _wheel(index, '2.0')
    (why,) = stale(root)
    assert 'Update dep' in why, why
    reasoned = _locked(root, _manifest(kit, index, '"dep<2",  # planted: 2.0 breaks the ABI'))
    assert stale(root) == (), 'a reasoned range resolves at the newest it admits'
    assert lock_problems(root, reasoned) == (), 'a reasoned range is admitted below latest'
    bare = _locked(root, _manifest(kit, index, '"dep<2",'))
    (why,) = lock_problems(root, bare)
    assert why == 'line 7: "dep<2" holds a requirement below the newest with no reason'


def test_a_resolution_that_cannot_reach_its_source_refuses_with_its_diagnosis(world: tuple[Path, Path, Path]) -> None:
    """PLANTED: the in-house source vanishes (the network is down) -- refused, never admitted unjudged."""
    root, kit, index = world
    _locked(root, _manifest(kit, index, '"dep",'))
    shutil.rmtree(kit, onexc=lambda func, path, _: (Path(path).chmod(0o700), func(path)))
    (why,) = stale(root)
    assert why.startswith(f'{UNRESOLVED} ('), why
    assert 'REFUSED' in why or 'gave up' in why, 'the netverb diagnosis is carried'


def test_no_lock_is_refused_on_the_forge_and_a_pinned_checkout_passes(tmp_path: Path) -> None:
    """PLANTED: a checkout committing no lock reds through the consumer body; committing one greens it."""
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    bare = _commit(root, {'pyproject.toml': '[project]\nname = "x"\nversion = "0"\n'})
    assert lock_problems(root, bare) == (
        f'{bare[:12]} commits no uv.lock: its environment would be whatever resolves on the day',
    )
    with pytest.raises(LockNotPinned, match=re.escape(REMEDY)):
        assert_the_lock_is_pinned(root)
    _commit(root, {'uv.lock': 'version = 1\n'})
    assert_the_lock_is_pinned(root)


def test_this_repo_pins_its_lock() -> None:
    assert_the_lock_is_pinned(Path(__file__).resolve().parents[1])


def test_the_remedy_names_a_door_an_agent_guard_admits() -> None:
    """A refusal's remedy must be runnable: it names the dep door, which no env-mutation row matches.

    PLANTED CONTROL: the bare spelling the remedy used to name is what a guard row refuses.
    """
    assert DOOR in REMEDY
    assert DOOR.split()[2:5] == ['-m', 'dev_lab.dev.dep', '--lock-upgrade']
    bare_uv_mutation = re.compile(r'(?:^|\s)uv\s+(?:add|remove|sync|lock)\b')
    assert not bare_uv_mutation.search(DOOR)
    assert bare_uv_mutation.search('uv lock --upgrade')


def test_a_hold_names_its_reason_on_its_line_or_the_line_above() -> None:
    text = (
        'requires-python = ">=3.13,<3.14"\n'
        '# `<3.14`: the pyo3 ABI\n'
        'requires-python = ">=3.13,<3.14"\n'
        'dependencies = ["a>=1", "b==2", "c~=1.0  ; python_version < \'3.13\'", "d!=3"]\n'
        'x = ["lab @ git+https://h/o/lab.git@' + 'a' * 40 + '", "lab @ git+https://h/o/lab.git"]\n'
        'install = "uv sync --frozen --all-extras"  # a reason-free non-requirement\n'
        'y = ["e<2"]  # held: e 2 drops Windows\n'
    )
    assert unreasoned_holds(text) == (
        'line 1: ">=3.13,<3.14"',
        'line 4: "b==2"',
        'line 4: "c~=1.0  ; python_version < \'3.13\'"',
        f'line 5: "lab @ git+https://h/o/lab.git@{"a" * 40}"',
    )


def test_no_family_pre_push_row_reads_the_lock_or_the_branch_set() -> None:
    """User ruling 2026-10-24: lock and branch set are judged on the forge only, never at a local push."""
    runs = {' '.join(row['run']) for row in base_rows()['pre-push']}
    assert not {run for run in runs if 'lockcheck' in run or 'branchset' in run or 'behind' in run}, runs


_GIT_EXE = shutil.which('git') or 'git'


def _git_ok(cwd: Path, *argv: str) -> str:
    return subprocess.run(
        [_GIT_EXE, *argv], cwd=cwd, check=True, capture_output=True, text=True, encoding='utf-8'
    ).stdout.strip()


def test_the_resolved_tree_carries_its_submodules(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C5: a path dependency into a submodule (a product's engine crate) must exist in the tree that is resolved.

    Planted control: HEAD moves past the mounted sha, so the tree is a fresh worktree, not the checkout.
    """
    # The test's engine is a local path; git refuses file:// submodules unless told, and only the env reaches
    # the clone `submodule update` runs.
    monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
    monkeypatch.setenv('GIT_CONFIG_KEY_0', 'protocol.file.allow')
    monkeypatch.setenv('GIT_CONFIG_VALUE_0', 'always')
    sub, repo = tmp_path / 'engine', tmp_path / 'product'
    for path in (sub, repo):
        path.mkdir()
        _git_ok(path, 'init', '-q', '-b', 'main')
        _git_ok(path, 'config', 'user.email', 't@t')
        _git_ok(path, 'config', 'user.name', 't')
    (sub / 'crate.txt').write_text('engine', encoding='utf-8')
    _git_ok(sub, 'add', 'crate.txt')
    _git_ok(sub, 'commit', '-qm', 'engine')
    _git_ok(repo, 'submodule', 'add', '-q', sub.as_uri(), 'components/engine')
    _git_ok(repo, 'commit', '-qm', 'mount')
    mounted = _git_ok(repo, 'rev-parse', 'HEAD')
    (repo / 'later.txt').write_text('x', encoding='utf-8')
    _git_ok(repo, 'add', 'later.txt')
    _git_ok(repo, 'commit', '-qm', 'later')
    shared = _git_ok(repo / 'components' / 'engine', 'rev-parse', '--git-dir')
    before = (Path(repo / 'components' / 'engine') / shared / 'config').read_text(encoding='utf-8')
    # A pre-push hook runs with GIT_DIR naming the repository pushing: the mount must not inherit it.
    monkeypatch.setenv('GIT_DIR', _git_ok(repo, 'rev-parse', '--absolute-git-dir'))
    with detached_worktree(repo, mounted) as tree:
        assert tree != repo, 'the control: HEAD moved on, so a separate tree is built'
        assert (tree / 'components' / 'engine' / 'crate.txt').is_file()
    monkeypatch.delenv('GIT_DIR')  # the checks below are the repository's own, outside the hook
    after = (Path(repo / 'components' / 'engine') / shared / 'config').read_text(encoding='utf-8')
    assert after == before, 'the submodule state every other checkout shares was written'
    assert _git_ok(repo / 'components' / 'engine', 'status', '--porcelain') == '', 'the checkout still works'


def test_the_pin_is_never_judged_on_freshness(world: tuple[Path, Path, Path]) -> None:
    """FRESHNESS is the forge relock's alone (user ruling 2026-10-22): the PIN reading never resolves.

    PLANTED CONTROL: the lock really is behind its kit and still pins; an unreasoned hold is still refused.
    """
    root, kit, index = world
    old = _locked(root, _manifest(kit, index, '"dep",'))
    _commit(kit, {'README': 'moved'})
    assert stale(root), 'CONTROL: the lock really is behind its kit'
    assert lock_problems(root, old) == ()
    unheld = _locked(root, _manifest(kit, index, '"dep<2",'))
    assert lock_problems(root, unheld)


def test_a_stale_lock_head_gets_a_red_forge_status_naming_the_relock(
    world: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """User ruling 2026-10-24: the forge says a stale lock on the PR head, ``failure`` with the one remedy.

    PLANTED CONTROL: the same head at the newest resolution is ``success``; a head already judged is not re-resolved.
    """
    posted: dict[str, list[tuple[str, str, str]]] = {}

    def post(_client: object, sha: str, *, context: str, state: str, description: str) -> None:
        posted.setdefault(sha, []).append((context, state, description))

    def listed(_client: object, sha: str) -> tuple[object, ...]:
        return tuple(type('S', (), {'context': one[0], 'state': one[1]})() for one in posted.get(sha, []))

    monkeypatch.setattr(forgeheadgate, 'status_post', post)
    monkeypatch.setattr(forgeheadgate, 'status_list', listed)
    root, kit, index = world
    fresh = _locked(root, _manifest(kit, index, '"dep",') + BRANCHSET)
    forgeheadgate.judge(root, None, fresh, 'pr/x')
    assert posted[fresh] == [
        ('branchset', 'success', 'pr/x is declared'),
        ('lock/fresh', 'success', 'uv.lock is the newest resolution'),
    ]
    _commit(kit, {'README': 'moved'})
    stale_head = _commit(root, {'x.txt': 'x'})
    assert forgeheadgate.judge(root, None, stale_head, 'lane/x') == ['branchset: failure', 'lock/fresh: failure']
    (_, state, text) = posted[stale_head][1]
    assert state == 'failure'
    assert text.startswith(f'stale uv.lock: {forgeheadgate.LOCK_REMEDY} (Update kit'), text
    assert f'run `{DOOR}`, then commit uv.lock' == forgeheadgate.LOCK_REMEDY
    assert 'lane/x is undeclared' in posted[stale_head][0][2]
    assert forgeheadgate.judge(root, None, stale_head, 'lane/x') == [], 'judged once per head sha'


BRANCHSET = """
[tool.dev_lab.branchset]
trunk = 'main'
sessions = ['integrate/main']
ephemeral = ['pr/*']
"""


def test_a_rust_repo_pins_one_exact_toolchain_version(tmp_path: Path) -> None:
    """User ruling 2026-10-25: the Rust toolchain is pinned like the lock -- one exact version, never a channel name.

    PLANTED control: the same repository pinned at an exact version, and one with no Rust, pass.
    """
    root = tmp_path / 'r'
    root.mkdir()
    _git(root, 'init', '-q', '-b', 'main')
    python = {'pyproject.toml': '[project]\nname = "x"\nversion = "0"\n', 'uv.lock': 'version = 1\n'}
    assert lock_problems(root, _commit(root, python)) == (), 'a repository with no Rust pins no toolchain'
    unpinned = _commit(root, {'Cargo.toml': '[workspace]\n'})
    assert lock_problems(root, unpinned) == (
        f'{unpinned[:12]} commits Rust but no rust-toolchain.toml: its toolchain would be whatever is installed',
    )
    for channel in ('stable', 'nightly', '1.99'):
        floating = _commit(root, {'rust-toolchain.toml': f'[toolchain]\nchannel = "{channel}"\n'})
        assert lock_problems(root, floating) == (
            f'{floating[:12]} rust-toolchain.toml pins channel "{channel}", not one exact version like "1.99.1"',
        )
    assert lock_problems(root, _commit(root, {'rust-toolchain.toml': '[toolchain]\nchannel = "1.99.1"\n'})) == ()


def _rustup(output: str) -> object:
    attempt = type('Attempt', (), {'output': output})()
    return type('Report', (), {'ok': True, 'remedy': '', 'attempts': (attempt,)})()


def test_the_newest_stable_is_what_rustup_check_reports() -> None:
    behind = (
        'stable-x86_64-pc-windows-msvc - Update available : 1.93.1 (01f6ddf75 2026-02-11) -> 1.99.1 (58cf8f9c3 '
        '2026-10-13)\nrustup - Update available : 1.28.2 -> 1.29.2\n'
    )
    current = 'stable-x86_64-unknown-linux-gnu - Up to date : 1.99.1 (58cf8f9c3 2026-10-13)\n'
    assert newest_stable(check=lambda: _rustup(behind)) == '1.99.1'
    assert newest_stable(check=lambda: _rustup(current)) == '1.99.1'
    # rustup 1.29 on the Ada login nodes: lower case, no space before the colon (measured 2026-10-26).
    ada = (
        'stable-x86_64-unknown-linux-gnu - update available: 1.99.0 (b940084d7 2026-09-28) -> 1.99.1 '
        '(58cf8f9c3 2026-10-13)\nrustup - update available : 1.29.1 -> 1.29.2\n'
    )
    assert newest_stable(check=lambda: _rustup(ada)) == '1.99.1'
    # rustup exits 100 when an update is available (measured on Ada 2026-10-26): the answer is in the output.
    updates = _rustup(ada)
    updates.ok = False
    assert newest_stable(check=lambda: updates) == '1.99.1'
    with pytest.raises(OSError, match='rustup check named no stable toolchain'):
        newest_stable(check=lambda: _rustup('nightly-x86_64 - Up to date : 1.100.0-nightly\n'))


def test_a_toolchain_behind_the_newest_stable_is_stale_and_pinning_moves_only_its_channel(tmp_path: Path) -> None:
    """PLANTED control: the same tree pinned at the newest stable is fresh."""
    (tmp_path / 'rust-toolchain.toml').write_text(
        '[toolchain]\nchannel = "1.99.0"\ncomponents = ["clippy"]\n', encoding='utf-8'
    )

    def fresh(_tree: Path) -> object:
        return _rustup('')

    assert stale(tmp_path, resolve=fresh, stable=lambda: '1.99.1') == (
        'rust-toolchain.toml is not the newest stable: 1.99.0 -> 1.99.1',
    )
    pin_stable(tmp_path, '1.99.1')
    assert (tmp_path / 'rust-toolchain.toml').read_text(encoding='utf-8') == (
        '[toolchain]\nchannel = "1.99.1"\ncomponents = ["clippy"]\n'
    )
    assert stale(tmp_path, resolve=fresh, stable=lambda: '1.99.1') == ()
    assert stale(tmp_path / 'none', resolve=fresh, stable=lambda: '9.9.9') == (), 'no toolchain, no reading'
