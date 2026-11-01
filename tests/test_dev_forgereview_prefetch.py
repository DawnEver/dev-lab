"""The door fetches the reviewed blobs before the reviewer runs: the reviewer holds no forge token.

Measured 2026-11-01 on the Gitea review of motronics #5397: in the job's blobless clone the reviewer's own
``git diff -M`` fetched blobs lazily and failed ``could not read Username`` -- by design it gets no credential
(:mod:`dev_lab.dev.reviewgitauth`). The door does hold one, so it asks for every blob the ranges change, at once.
"""

from __future__ import annotations

from pathlib import Path

from _forge_fake import git_out, run_git

from dev_lab.dev.forgereview_scope import prefetch


def _origin_and_partial_clone(tmp_path: Path) -> tuple[Path, str, str]:
    origin = tmp_path / 'origin'
    origin.mkdir()
    run_git(origin, 'init', '-q', '-b', 'main')
    for key, value in (('user.name', 't'), ('user.email', 't@t'), ('uploadpack.allowFilter', 'true'),
                       ('uploadpack.allowAnySHA1InWant', 'true')):  # fmt: skip
        run_git(origin, 'config', key, value)
    (origin / 'kept.txt').write_text('kept\n', encoding='utf-8')
    (origin / 'changed.txt').write_text('before\n', encoding='utf-8')
    run_git(origin, 'add', '.')
    run_git(origin, 'commit', '-q', '-m', 'base')
    base = git_out(origin, 'rev-parse', 'HEAD')
    (origin / 'changed.txt').write_text('after\n', encoding='utf-8')
    (origin / 'added.txt').write_text('new\n', encoding='utf-8')
    run_git(origin, 'add', '.')
    run_git(origin, 'commit', '-q', '-m', 'head')
    head = git_out(origin, 'rev-parse', 'HEAD')
    clone = tmp_path / 'clone'
    run_git(tmp_path, 'clone', '-q', '--no-checkout', '--filter=blob:none', origin.as_uri(), str(clone))
    return clone, base, head


def _missing(clone: Path, *revs: str) -> set[str]:
    """The objects *revs* reach that the clone lacks (``--missing=print`` lists them, never fetching)."""
    listed = git_out(clone, 'rev-list', '--objects', '--missing=print', *revs)
    return {line[1:] for line in listed.splitlines() if line.startswith('?')}


def test_a_partial_clone_holds_every_blob_the_range_changes_after_the_prefetch(tmp_path: Path) -> None:
    clone, base, head = _origin_and_partial_clone(tmp_path)
    changed = {git_out(clone, 'rev-parse', f'{rev}:{path}') for rev, path in
               ((base, 'changed.txt'), (head, 'changed.txt'), (head, 'added.txt'))}  # fmt: skip
    assert changed <= _missing(clone, base, head), 'the planted clone lacks them (PLANTED CONTROL)'
    assert prefetch(clone, f'{base}..{head}') == len(changed)
    assert not changed & _missing(clone, base, head)
    assert git_out(clone, 'rev-parse', f'{head}:kept.txt') in _missing(clone, head), 'an unchanged blob stays out'


def test_a_full_clone_asks_for_nothing(tmp_path: Path) -> None:
    _, base, head = _origin_and_partial_clone(tmp_path)
    full = tmp_path / 'full'
    run_git(tmp_path, 'clone', '-q', '--no-checkout', str(tmp_path / 'origin'), str(full))
    assert prefetch(full, f'{base}..{head}') == 0
