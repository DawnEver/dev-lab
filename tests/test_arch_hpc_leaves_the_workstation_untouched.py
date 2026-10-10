"""A cluster run leaves the local workstation untouched (user ruling 2026-10-09).

THE INVARIANT. :mod:`lab_commons.hpc` never imports the box lock or an environment seat (nothing in
``lab_commons.dev``), never runs pytest or any interpreter locally, and its only local subprocesses are
READ-ONLY git; its only local write is the record path given by ``-o``. Measured before the fix: the
bundle step wrote a temporary ``refs/lab-ci/<sha>`` into the caller's checkout, and the run was one
local process waiting hours on the cluster.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from test_hpc_run import MACHINE, FakeRunCluster

from lab_commons.hpc import __main__ as cli
from lab_commons.hpc.shell import pack

_GIT: Final = shutil.which('git') or 'git'

#: The git subcommands a run may run here; each one only READS the repository.
READ_ONLY_GIT = frozenset({'show', 'for-each-ref', 'pack-objects', 'rev-parse', 'ls-remote'})


def _git(repo: Path, *args: str, stdin: bytes | None = None) -> bytes:
    return subprocess.run([_GIT, '-C', str(repo), *args], input=stdin, capture_output=True, check=True).stdout


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q')
    (repo / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    _git(repo, 'add', 'pyproject.toml')
    _git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'one')
    return repo, _git(repo, 'rev-parse', 'HEAD').decode().strip()


def _fingerprint(repo: Path) -> dict[str, str]:
    """Every file under ``.git`` by content hash -- refs, index, objects, config."""
    git = repo / '.git'
    return {str(p.relative_to(git)): hashlib.sha256(p.read_bytes()).hexdigest() for p in git.rglob('*') if p.is_file()}


def test_hpc_imports_nothing_of_the_box_lock_or_the_environment_seats() -> None:
    probe = (
        'import importlib, pkgutil, sys, lab_commons.hpc as h\n'
        "for m in pkgutil.iter_modules(h.__path__): importlib.import_module('lab_commons.hpc.' + m.name)\n"
        "print('\\n'.join(sorted(k for k in sys.modules if k.startswith('lab_commons.dev'))))\n"
    )
    out = subprocess.run(
        [sys.executable, '-c', probe], capture_output=True, text=True, encoding='utf-8', check=True
    ).stdout
    assert out.split() == [], 'lab_commons.hpc reaches lab_commons.dev (box lock, env seats) -- it must not'


def test_the_pack_reads_the_repository_and_the_cluster_cache_can_index_it(tmp_path: Path) -> None:
    repo, sha = _repo(tmp_path)
    before = _fingerprint(repo)
    shipped = base64.b64decode(pack(repo, sha))
    assert _fingerprint(repo) == before, 'the caller repository is byte-identical: no ref, no index, no object'
    cache = tmp_path / 'cache.git'
    subprocess.run([_GIT, 'init', '-q', '--bare', str(cache)], check=True)
    _git(cache, 'index-pack', '--stdin', stdin=shipped)
    assert _git(cache, 'cat-file', '-t', sha).strip() == b'commit'


def test_submit_and_gather_run_only_read_only_git_here_and_write_only_the_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, sha = _repo(tmp_path)
    fake = FakeRunCluster(have=False)
    real_popen = subprocess.Popen
    spawned: list[list[str]] = []

    def have_after_pack(command: str, stdin: str | None = None) -> str:
        if 'packs/' in command and 'base64 -d' in command:
            fake.have = True
        return fake(command.replace(sha, 'a' * 40), stdin)

    def spy(argv: list[str], *args: object, **kw: object) -> subprocess.Popen[bytes]:
        spawned.append(list(argv))
        is_git = Path(str(argv[0])).stem == 'git'
        if not (is_git and argv[3] in READ_ONLY_GIT):
            pytest.fail(f'a local subprocess other than read-only git: {argv}')
        return real_popen(argv, *args, **kw)  # type: ignore[call-overload]

    monkeypatch.setattr(cli, 'load_grants', lambda: MACHINE)
    monkeypatch.setattr(cli, 'runner_for', lambda _g, *_a: have_after_pack)
    monkeypatch.setattr(subprocess, 'Popen', spy)
    before_repo, before_dir = _fingerprint(repo), sorted(tmp_path.rglob('*'))
    common = ['--sha', sha]
    assert cli.main(['run', 'submit', *common, '--scope', 'full', '--repo-url', 'https://g/r.git',
                     '--install', 'true', '--repo', str(repo)]) == 0  # fmt: skip
    assert json.loads(fake.state)['sha'] == sha, 'the run state went to the cluster'
    out = tmp_path / 'out'
    assert cli.main(['run', 'gather', *common, '-o', str(out)]) == 0
    (output,) = out.iterdir()
    assert output.name.startswith(f'run-{sha}-linux-'), output.name
    assert {argv[3] for argv in spawned} <= READ_ONLY_GIT
    assert 'pack-objects' in {argv[3] for argv in spawned}, 'the commit was off the remote, so it was packed'
    assert _fingerprint(repo) == before_repo
    assert sorted(tmp_path.rglob('*')) == sorted([*before_dir, out, output]), 'only the record under -o was written'
