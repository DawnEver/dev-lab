"""The door reads the base's declaration in a blobless clone through its own git credential.

Measured 2026-11-02 on every Gitea review of a consumer (14 runs): ``trusted_integration`` read
``origin/integrate/main:pyproject.toml`` with a plain ``git show`` that carried no credential, so the lazy blob
fetch of the job's ``--filter=blob:none`` clone failed (exit 128) and the review refused. The door's git calls
carry the held header (:func:`dev_lab.dev.reviewgitauth.git_env`); the reviewer's never do. Here the held slot is
an ``insteadOf`` that alone makes origin reachable -- the stand-in for the auth header a private forge needs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev import reviewgitauth
from dev_lab.dev.forgereview_declared import review_at, trusted_integration

_UNREACHABLE = 'https://forge.invalid/repo.git'
_MANIFEST = '[tool.dev_lab.integrator]\nintegration = "main"\n\n[tool.dev_lab.review]\nclaim_stale = "2 h"\n'


class _Forge:
    repo = 'repos/o/r'

    def call(self, _method: str, _path: str) -> dict[str, str]:
        return {'default_branch': 'main'}


def _blobless(tmp_path: Path) -> tuple[Path, str]:
    origin = tmp_path / 'origin'
    origin.mkdir()
    run_git(origin, 'init', '-q', '-b', 'main')
    for key, value in (('user.name', 't'), ('user.email', 't@t'), ('uploadpack.allowFilter', 'true'),
                       ('uploadpack.allowAnySHA1InWant', 'true')):  # fmt: skip
        run_git(origin, 'config', key, value)
    (origin / 'pyproject.toml').write_text(_MANIFEST, encoding='utf-8')
    run_git(origin, 'add', '.')
    run_git(origin, 'commit', '-q', '-m', 'base')
    clone = tmp_path / 'clone'
    run_git(tmp_path, 'clone', '-q', '--no-checkout', '--filter=blob:none', origin.as_uri(), str(clone))
    run_git(clone, 'remote', 'set-url', 'origin', _UNREACHABLE)  # reachable only through the door's held slot
    return clone, origin.as_uri()


def test_the_door_reads_the_declaration_a_plain_git_show_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, uri = _blobless(tmp_path)
    monkeypatch.setenv('GIT_TERMINAL_PROMPT', '0')
    with pytest.raises(subprocess.CalledProcessError):  # a credential-less read fails here (PLANTED CONTROL)
        run_git(clone, 'show', 'origin/main:pyproject.toml')
    monkeypatch.setattr(reviewgitauth, '_held', {'key': f'url.{uri}.insteadOf', 'value': _UNREACHABLE})
    assert trusted_integration(clone, _Forge()) == 'main'  # type: ignore[arg-type]
    assert review_at(clone, 'main').claim_stale == '2 h'
    assert git_out(clone, 'config', '--get', 'remote.origin.url') == _UNREACHABLE, 'nothing persisted in the clone'
