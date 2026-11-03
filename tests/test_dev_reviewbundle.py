"""A review bundle is built from the diff's files only, and the judge refuses one it cannot trust.

PREPARE runs on the untrusted runner and holds no reviewer token; JUDGE runs on the reviewer host and never
executes PR content. The planted controls: a tampered byte, a stale head, a file whose content is not the blob
the diff names, and a forge diff the bundle does not match are each refused; the judge's only process is the
declared command.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev import reviewbundle
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev.reviewbundle import BundleRefused

#: CRLF, a non-UTF-8 byte and a NUL: the bytes a text-mode read would change.
_RAW = b'a\r\n\xff\x00'


def _rewritten(forged: dict[str, object]) -> bytes:
    return json.dumps(forged, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / 'repo'
    root.mkdir()
    run_git(root, 'init', '-q', '-b', 'main')
    run_git(root, 'config', 'user.name', 't')
    run_git(root, 'config', 'user.email', 't@t')
    (root / 'pyproject.toml').write_text('[tool.dev_lab.review]\nquiet = "1 min"\n', encoding='utf-8')
    (root / 'kept.py').write_text('x = 1\n', encoding='utf-8')
    (root / 'gone.py').write_text('y = 2\n', encoding='utf-8')
    (root / 'untouched.py').write_text('z = 3\n', encoding='utf-8')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'base')
    base = git_out(root, 'rev-parse', 'HEAD')
    (root / 'kept.py').write_text('x = 10\n', encoding='utf-8')
    (root / 'gone.py').unlink()
    (root / 'new.py').write_text('w = 4\n', encoding='utf-8')
    (root / 'crlf.bin').write_bytes(_RAW)
    run_git(root, 'add', '-A', '.')
    run_git(root, 'commit', '-q', '-m', 'head')
    return root, base, git_out(root, 'rev-parse', 'HEAD')


def _pull(head: str, *, number: int = 7, base: str = 'main') -> PullRequest:
    return PullRequest(number, 't', 'open', '', '', 'a', 'pr/x', base, head_sha=head)


def _built(tmp_path: Path) -> tuple[reviewbundle.Bundle, str, str]:
    root, base, head = _repo(tmp_path)
    return reviewbundle.prepare(root, repo='o/r', pull=_pull(head), base=base), base, head


def test_prepare_holds_only_the_changed_files_both_sides(tmp_path: Path) -> None:
    bundle, base, head = _built(tmp_path)
    by_path = {one.path: one for one in bundle.files}
    assert sorted(by_path) == ['crlf.bin', 'gone.py', 'kept.py', 'new.py']  # untouched.py is never read
    assert (by_path['kept.py'].side('base'), by_path['kept.py'].side('head')) == (b'x = 1\n', b'x = 10\n')
    assert by_path['crlf.bin'].side('head') == _RAW
    assert by_path['gone.py'].head is None
    assert by_path['new.py'].base is None
    assert (bundle.base_sha, bundle.head_sha, bundle.pr, bundle.repo) == (base, head, 7, 'o/r')
    assert 'quiet = "1 min"' in bundle.declaration
    assert 'diff --git a/kept.py b/kept.py' in bundle.diff


def test_a_bundle_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    data, digest = reviewbundle.dump(bundle)
    assert reviewbundle.dump(reviewbundle.load(data, digest)) == (data, digest)


def test_a_tampered_byte_is_refused(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    data, digest = reviewbundle.dump(bundle)
    with pytest.raises(BundleRefused, match='hash'):
        reviewbundle.load(data.replace(b'"pr":7', b'"pr":8'), digest)


def test_content_that_is_not_the_named_blob_is_refused(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    data, _ = reviewbundle.dump(bundle)
    forged = json.loads(data)
    forged['files'][[f['path'] for f in forged['files']].index('kept.py')]['head'] = 'aW1wb3J0IG9zCg=='  # import os
    rewritten = _rewritten(forged)
    with pytest.raises(BundleRefused, match=r'kept\.py'):
        reviewbundle.load(rewritten, reviewbundle.digest_of(rewritten))


def test_a_stale_head_or_another_pull_is_refused(tmp_path: Path) -> None:
    bundle, _, head = _built(tmp_path)
    reviewbundle.current(bundle, _pull(head), repo='o/r')
    with pytest.raises(BundleRefused, match='head'):
        reviewbundle.current(bundle, _pull('f' * 40), repo='o/r')
    with pytest.raises(BundleRefused, match='pull'):
        reviewbundle.current(bundle, _pull(head, number=8), repo='o/r')
    with pytest.raises(BundleRefused, match='base'):
        reviewbundle.current(bundle, _pull(head, base='dev'), repo='o/r')


def test_the_forges_own_diff_must_name_the_bundles_blobs(tmp_path: Path) -> None:
    root, base, head = _repo(tmp_path)
    bundle = reviewbundle.prepare(root, repo='o/r', pull=_pull(head), base=base)
    reviewbundle.matches_forge(bundle, git_out(root, 'diff', base, head))
    run_git(root, 'commit', '-q', '--allow-empty', '-m', 'noop')
    (root / 'kept.py').write_text('x = 99\n', encoding='utf-8')
    run_git(root, 'commit', '-q', '-am', 'other')
    with pytest.raises(BundleRefused, match='forge'):
        reviewbundle.matches_forge(bundle, git_out(root, 'diff', base, 'HEAD'))


def test_the_judge_runs_only_the_declared_command_on_plain_files(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    seen: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...]) -> str:
        seen.append(argv)
        tree = Path(argv[-1])
        assert (tree / 'head' / 'kept.py').read_bytes() == b'x = 10\n'
        assert (tree / 'head' / 'crlf.bin').read_bytes() == _RAW
        assert (tree / 'base' / 'gone.py').is_file()
        assert not (tree / 'head' / 'gone.py').exists()
        assert not (tree / '.git').exists()
        return '{"findings": []}'

    out = reviewbundle.judge(bundle, ('reviewer', '--bundle', reviewbundle.BUNDLE_FIELD), run=run)
    assert out == '{"findings": []}'
    assert len(seen) == 1
    assert seen[0][:2] == ('reviewer', '--bundle')


def test_the_judge_refuses_a_command_that_would_run_git(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    with pytest.raises(BundleRefused, match='git'):
        reviewbundle.judge(bundle, ('git', 'checkout', reviewbundle.BUNDLE_FIELD), run=lambda _argv: '')


def test_a_path_escaping_the_tree_is_refused(tmp_path: Path) -> None:
    bundle, _, _ = _built(tmp_path)
    data, _ = reviewbundle.dump(bundle)
    forged = json.loads(data)
    forged['files'][0]['path'] = '../escape.py'
    rewritten = _rewritten(forged)
    with pytest.raises(BundleRefused, match='escape'):
        reviewbundle.load(rewritten, reviewbundle.digest_of(rewritten))
