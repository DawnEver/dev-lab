"""A review bundle is built from the diff's files only, and the judge refuses one it cannot trust.

PREPARE runs on the untrusted runner and holds no reviewer token; JUDGE runs on the reviewer host and never
executes PR content, trusting nothing the producer wrote that it can read from the forge (D3). The planted controls:
a tampered byte, a stale head or merge base, a file whose content is not the blob the diff names, a malformed
document, a forge diff the bundle does not match (a quoted path, a rename, a mode change) are each refused, while the
honest bundle passes; binary is the judge's verdict from the bytes, never the head's ``.gitattributes``; the reviewer
reads the forge's diff; and a git the judge's command starts finds no repository.
"""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import lab_commons.launch as _door
import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev import reviewbundle
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev.reviewbundle import BundleRefused

#: CRLF, a non-UTF-8 byte and a NUL: binary by its bytes.
_RAW = b'a\r\n\xff\x00'
_ODD = 'é b/x.py'  # quoted by git (non-ASCII) and holding ' b/'


def _rewritten(forged: object) -> bytes:
    return json.dumps(forged, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    root = tmp_path / 'repo'
    root.mkdir()
    run_git(root, 'init', '-q', '-b', 'main')
    run_git(root, 'config', 'user.name', 't')
    run_git(root, 'config', 'user.email', 't@t')
    (root / 'kept.py').write_text('x = 1\n', encoding='utf-8')
    (root / 'gone.py').write_text('y = 2\n', encoding='utf-8')
    (root / 'moved.py').write_text('m = 5\n' * 20, encoding='utf-8')
    (root / 'mode.sh').write_text('echo\n', encoding='utf-8')
    # bytes: a text-mode write is CRLF on Windows, which autocrlf stores as LF in the base and the head's
    # '*.py binary' stores as CRLF -- a change to a file the head never touched.
    (root / 'untouched.py').write_bytes(b'z = 3\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'base')
    base = git_out(root, 'rev-parse', 'HEAD')
    run_git(root, 'update-ref', 'refs/remotes/origin/main', base)
    (root / 'kept.py').write_bytes(b'x = 10\n')  # bytes: the head's attributes turn off line-ending conversion
    (root / 'gone.py').unlink()
    (root / 'new.py').write_text('w = 4\n', encoding='utf-8')
    (root / 'crlf.bin').write_bytes(_RAW)
    (root / '.gitattributes').write_text('*.py binary\n', encoding='utf-8')  # the author calls source binary
    (root / _ODD).parent.mkdir()
    (root / _ODD).write_text('q = 6\n', encoding='utf-8')
    run_git(root, 'mv', 'moved.py', 'renamed.py')
    run_git(root, 'add', '-A', '.')
    # after the add: with core.fileMode on (Linux) `add` re-reads the worktree's 0644 and drops an earlier +x
    run_git(root, 'update-index', '--chmod=+x', 'mode.sh')
    run_git(root, 'commit', '-q', '-m', 'head')
    return root, base, git_out(root, 'rev-parse', 'HEAD')


def _pull(head: str, *, number: int = 7, base: str = 'main') -> PullRequest:
    return PullRequest(number, 't', 'open', '', '', 'a', 'pr/x', base, head_sha=head)


def _built(tmp_path: Path) -> tuple[reviewbundle.Bundle, Path, str, str]:
    root, base, head = _repo(tmp_path)
    return reviewbundle.prepare(root, repo='o/r', pull=_pull(head)), root, base, head


def _forge_diff(root: Path, base: str, head: str, *flags: str) -> str:
    """What a forge serves: git's own diff, renames detected unless *flags* say otherwise."""
    return git_out(root, '-c', 'core.quotePath=true', 'diff', '--full-index', *flags, base, head)


def _without(bundle: reviewbundle.Bundle, path: str) -> reviewbundle.Bundle:
    return dataclasses.replace(bundle, files=tuple(f for f in bundle.files if f.path != path))


def test_prepare_holds_only_the_changed_files_both_sides(tmp_path: Path) -> None:
    bundle, _, base, head = _built(tmp_path)
    by_path = {one.path: one for one in bundle.files}
    assert sorted(by_path) == sorted(
        ['.gitattributes', 'crlf.bin', 'gone.py', 'kept.py', 'mode.sh', 'moved.py', 'new.py', 'renamed.py', _ODD]
    )  # untouched.py is never read; the rename is split
    assert (by_path['kept.py'].side('base'), by_path['kept.py'].side('head')) == (b'x = 1\n', b'x = 10\n')
    assert by_path['crlf.bin'].side('head') == _RAW
    assert by_path['gone.py'].head is None
    assert by_path['new.py'].base is None
    assert (bundle.base_sha, bundle.head_sha, bundle.pr, bundle.repo) == (base, head, 7, 'o/r')


def test_binary_is_the_bytes_verdict_never_the_heads_gitattributes(tmp_path: Path) -> None:
    """PLANTED CONTROL: crlf.bin holds a NUL and is binary; kept.py, which the head's attributes call binary, is not."""
    bundle, _, _, _ = _built(tmp_path)
    by_path = {one.path: one for one in bundle.files}
    assert by_path['crlf.bin'].binary
    assert not by_path['kept.py'].binary


def test_a_bundle_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    data, digest = reviewbundle.dump(bundle)
    assert reviewbundle.dump(reviewbundle.load(data, digest)) == (data, digest)
    assert 'diff' not in json.loads(data)  # the reviewer reads the forge's diff, never the producer's
    assert 'declaration' not in json.loads(data)  # the declaration is read from the forge


def test_a_tampered_byte_is_refused(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    data, digest = reviewbundle.dump(bundle)
    with pytest.raises(BundleRefused, match='hash'):
        reviewbundle.load(data.replace(b'"pr":7', b'"pr":8'), digest)


@pytest.mark.parametrize('forged', [[], {'version': 2}, {'version': 2, 'files': 'x'}, 'not json'])
def test_a_malformed_bundle_is_refused_never_raised_raw(forged: object) -> None:
    data = forged.encode() if isinstance(forged, str) else _rewritten(forged)
    with pytest.raises(BundleRefused):
        reviewbundle.load(data, reviewbundle.digest_of(data))


def test_content_that_is_not_the_named_blob_is_refused(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    data, _ = reviewbundle.dump(bundle)
    forged = json.loads(data)
    forged['files'][[f['path'] for f in forged['files']].index('kept.py')]['head'] = 'aW1wb3J0IG9zCg=='  # import os
    rewritten = _rewritten(forged)
    with pytest.raises(BundleRefused, match=r'kept\.py'):
        reviewbundle.load(rewritten, reviewbundle.digest_of(rewritten))


def test_a_stale_head_another_pull_or_another_merge_base_is_refused(tmp_path: Path) -> None:
    bundle, _, base, head = _built(tmp_path)
    reviewbundle.current(bundle, _pull(head), repo='o/r', merge_base=base)
    with pytest.raises(BundleRefused, match='head'):
        reviewbundle.current(bundle, _pull('f' * 40), repo='o/r', merge_base=base)
    with pytest.raises(BundleRefused, match='pull'):
        reviewbundle.current(bundle, _pull(head, number=8), repo='o/r', merge_base=base)
    with pytest.raises(BundleRefused, match='base'):
        reviewbundle.current(bundle, _pull(head, base='dev'), repo='o/r', merge_base=base)
    with pytest.raises(BundleRefused, match='merge base'):
        reviewbundle.current(bundle, _pull(head), repo='o/r', merge_base='e' * 40)


@pytest.mark.parametrize('flags', [(), ('--no-renames',)])
def test_the_forges_own_diff_must_name_the_bundles_blobs(tmp_path: Path, flags: tuple[str, ...]) -> None:
    """Renames, a mode-only change and a quoted path holding ' b/' all match the honest bundle, either way."""
    bundle, root, base, head = _built(tmp_path)
    diff = _forge_diff(root, base, head, *flags)
    assert '"a/' in diff  # the quoted header is really in play
    reviewbundle.matches_forge(bundle, diff)
    (root / 'kept.py').write_text('x = 99\n', encoding='utf-8')
    run_git(root, 'commit', '-q', '-am', 'other')
    with pytest.raises(BundleRefused, match='forge'):
        reviewbundle.matches_forge(bundle, _forge_diff(root, base, 'HEAD', *flags))


@pytest.mark.parametrize('dropped', [_ODD, 'renamed.py', 'mode.sh'])
def test_a_bundle_omitting_any_file_the_forge_diff_names_is_refused(tmp_path: Path, dropped: str) -> None:
    bundle, root, base, head = _built(tmp_path)
    with pytest.raises(BundleRefused, match='forge diff changes'):
        reviewbundle.matches_forge(_without(bundle, dropped), _forge_diff(root, base, head))


def test_a_rename_whose_bytes_the_bundle_changed_is_refused(tmp_path: Path) -> None:
    bundle, root, base, head = _built(tmp_path)
    files = tuple(
        reviewbundle.Changed(f.path, f.base_blob, 'f' * 40, f.base, f.head) if f.path == 'renamed.py' else f
        for f in bundle.files
    )
    swapped = dataclasses.replace(bundle, files=files)
    with pytest.raises(BundleRefused, match=r'renamed\.py'):
        reviewbundle.matches_forge(swapped, _forge_diff(root, base, head))


def test_a_header_the_judge_cannot_parse_is_refused(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    with pytest.raises(BundleRefused, match='cannot parse'):
        reviewbundle.matches_forge(bundle, 'diff --git a/x.py c/y.py\nindex 1..2 100644\n')


def test_the_judge_reads_the_forges_diff_on_plain_files_with_no_repository(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    seen: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], env: dict[str, str]) -> str:
        seen.append(argv)
        tree = Path(argv[-1])
        assert (tree / 'head' / 'kept.py').read_bytes() == b'x = 10\n'
        assert not (tree / 'head' / 'crlf.bin').exists()  # a binary is listed, never written
        assert (tree / 'base' / 'gone.py').is_file()
        assert not (tree / 'head' / 'gone.py').exists()
        assert not (tree / '.git').exists()
        assert (tree / 'diff.patch').read_text(encoding='utf-8') == 'THE FORGE DIFF'
        assert env == reviewbundle.no_repo_env(tree)
        return '{"findings": []}'

    out = reviewbundle.judge(
        bundle, ('reviewer', '--bundle', reviewbundle.BUNDLE_FIELD), diff='THE FORGE DIFF', run=run
    )
    assert out == '{"findings": []}'
    assert len(seen) == 1


def test_the_materialized_bundle_json_carries_the_judges_binary_verdict(tmp_path: Path) -> None:
    """The reviewer (ai-lab ``BundleSource``) reads each file's ``binary`` from ``bundle.json``: the judge's verdict.

    PLANTED CONTROL: crlf.bin holds a NUL and says ``binary: true``; kept.py, which the head's attributes call
    binary, says ``false``. The document is the bundle's own :data:`~reviewbundle.VERSION`.
    """
    bundle, _, _, _ = _built(tmp_path)
    seen: dict[str, object] = {}

    def run(argv: tuple[str, ...], _env: dict[str, str]) -> str:
        seen.update(json.loads((Path(argv[-1]) / 'bundle.json').read_bytes()))
        return ''

    reviewbundle.judge(bundle, ('reviewer', reviewbundle.BUNDLE_FIELD), diff='', run=run)
    rows = {row['path']: row for row in seen['files']}
    assert seen['version'] == reviewbundle.VERSION
    assert rows['crlf.bin']['binary'] is True
    assert rows['kept.py']['binary'] is False


def test_a_git_started_under_the_judges_environment_finds_no_repository(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same git in the same directory, without the overrides, finds the repository."""
    root, _, _ = _repo(tmp_path)
    inside = root / 'sub'
    inside.mkdir()
    ask = ['git', 'rev-parse', '--git-dir']
    plain = _door.run(ask, cwd=inside, capture_output=True, check=False)
    assert plain.returncode == 0
    walled = _door.run(
        ask, cwd=inside, capture_output=True, check=False, env={**os.environ, **reviewbundle.no_repo_env(inside)}
    )
    assert walled.returncode != 0


@pytest.mark.parametrize('git', ['git', 'GIT.EXE', '/usr/bin/git'])
def test_the_judge_refuses_a_command_that_names_git(tmp_path: Path, git: str) -> None:
    bundle, _, _, _ = _built(tmp_path)
    with pytest.raises(BundleRefused, match='git'):
        reviewbundle.judge(bundle, (git, 'log', reviewbundle.BUNDLE_FIELD), diff='', run=lambda _a, _e: '')


def test_a_path_escaping_the_tree_is_refused(tmp_path: Path) -> None:
    bundle, _, _, _ = _built(tmp_path)
    data, _ = reviewbundle.dump(bundle)
    forged = json.loads(data)
    forged['files'][0]['path'] = '../escape.py'
    rewritten = _rewritten(forged)
    with pytest.raises(BundleRefused, match='escape'):
        reviewbundle.load(rewritten, reviewbundle.digest_of(rewritten))
