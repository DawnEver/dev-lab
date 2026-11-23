"""``dev_lab.dev.storage``: dev-lab's one adapter onto the storage kinds, and its where/render/migrate doors."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from lab_commons.storage import StorageError, declared

from dev_lab.dev import storage
from dev_lab.dev.artefactstores import SCRATCH_PREFIX, ArtefactRefused, check_key
from dev_lab.dev.writeroots import Root, excluded_paths, refuse_outside_tree

GIT = shutil.which('git') or 'git'


def _repo(tmp_path: Path, name: str = 'repo-a') -> Path:
    tree = tmp_path / name
    tree.mkdir()
    subprocess.run([GIT, 'init', '-q', str(tree)], check=True)
    return tree


def _bound(**roots: str) -> object:
    return declared({'storage': {'roots': roots}}, {})


def test_an_unbound_output_stays_in_the_checkout(tmp_path: Path) -> None:
    """PLANTED CONTROL for the binding: nothing declared, every writer's output/... is the checkout's."""
    tree = _repo(tmp_path)
    assert (
        storage.output_path(tree, 'forge', 'outbox', declared=declared({}, {}))
        == tree.resolve() / 'output/forge/outbox'
    )


def test_a_bound_output_moves_every_writer_with_the_main_checkout_name(tmp_path: Path) -> None:
    tree = _repo(tmp_path)
    bound = _bound(output=str(tmp_path / 'big' / '{repo}'))
    assert storage.output_path(tree, 'runcache', declared=bound) == tmp_path / 'big' / 'repo-a' / 'runcache'


def test_migrate_moves_the_tree_once_and_a_later_leftover_is_refused(tmp_path: Path) -> None:
    tree = _repo(tmp_path)
    (tree / 'output' / 'logs').mkdir(parents=True)
    (tree / 'output' / 'logs' / 'a.log').write_text('x', encoding='utf-8')
    bound = _bound(output=str(tmp_path / 'big' / '{repo}'))
    target = storage.migrate('output', tree, declared=bound)
    assert (target / 'logs' / 'a.log').read_text(encoding='utf-8') == 'x'
    assert (target / storage.MARKER).is_file()
    assert not (tree / 'output').exists()
    assert storage.migrate('output', tree, declared=bound) == target, 'a second migrate is a no-op'
    (tree / 'output').mkdir()
    (tree / 'output' / 'stray').write_text('y', encoding='utf-8')
    with pytest.raises(storage.StaleTree, match=r'holds .output. data'):
        storage.refuse_stale('output', tree, declared=bound)


def test_migrate_refuses_an_unbound_kind_and_a_foreign_target(tmp_path: Path) -> None:
    tree = _repo(tmp_path)
    with pytest.raises(StorageError, match='not bound on this machine'):
        storage.migrate('output', tree, declared=declared({}, {}))
    foreign = tmp_path / 'big' / 'repo-a'
    foreign.mkdir(parents=True)
    (foreign / 'theirs').write_text('z', encoding='utf-8')
    with pytest.raises(StorageError, match='not empty and carries no'):
        storage.migrate('output', tree, declared=_bound(output=str(tmp_path / 'big' / '{repo}')))


def _reaching(tmp_path: Path) -> object:
    remote = {
        'type': 's3', 'endpoint': 'https://objects.example', 'access_key_id': 'AKIA-declared',
        'secret_keys': ['secret_access_key'],
    }  # fmt: skip
    machine = {'storage': {'reach': {'results': {'credentials_file': str(tmp_path / 'secrets' / 'results')}}}}
    return declared(machine, {'storage': {'remotes': {'results': remote}}})


def test_render_joins_family_options_and_the_placed_secret_outside_the_repo(tmp_path: Path) -> None:
    """The declared access key ID and the placed secret meet only in the render."""
    tree = _repo(tmp_path)
    reach = _reaching(tmp_path)
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'results').write_text('secret_access_key = "s3cr3t"\n', encoding='utf-8')
    out = storage.render(tmp_path / 'conf' / 'rclone.conf', repo=tree, declared=reach)
    assert out.read_text(encoding='utf-8') == (
        '[results]\ntype = s3\nendpoint = https://objects.example\naccess_key_id = AKIA-declared\n'
        'secret_access_key = s3cr3t\n'
    )


def test_render_refuses_a_placed_file_restating_a_fact_and_names_the_migration(tmp_path: Path) -> None:
    """D51: an older file holding the access key ID is refused by name with its one-time migration."""
    tree = _repo(tmp_path)
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'results').write_text(
        'access_key_id = "AKIA-declared"\nsecret_access_key = "s3cr3t"\n', encoding='utf-8'
    )
    with pytest.raises(StorageError, match=r'restates .access_key_id.*secretplace migrate --remote results'):
        storage.render(tmp_path / 'rclone.conf', repo=tree, declared=_reaching(tmp_path))


def test_render_refuses_a_missing_secret_and_a_path_inside_the_repo(tmp_path: Path) -> None:
    tree = _repo(tmp_path)
    reach = _reaching(tmp_path)
    with pytest.raises(
        StorageError, match=r'no secret for remote .results. at its declared credentials_file .*results'
    ):
        storage.render(tmp_path / 'rclone.conf', repo=tree, declared=reach)
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'results').write_text('type = "s3"\n', encoding='utf-8')
    with pytest.raises(StorageError, match=r'restates .type.'):
        storage.rendered(reach)
    with pytest.raises(ValueError, match='never in a repo'):
        storage.render(tree / 'rclone.conf', repo=tree, declared=reach)


def test_a_bound_storage_root_is_admitted_by_the_write_guard_and_nothing_else(tmp_path: Path) -> None:
    """PLANTED CONTROL: a write under a write-prone root is refused unless it is under a bound storage root."""
    prone = (Root(tmp_path / 'tmp', 'temp'),)
    bound = _bound(output=str(tmp_path / 'tmp' / 'work' / '{repo}'))

    admitted = excluded_paths(prone, machine={}, env={}, storage=bound)
    assert refuse_outside_tree(tmp_path / 'tmp' / 'work' / 'repo-a' / 'x', roots=prone, excluded=admitted) is None
    assert refuse_outside_tree(tmp_path / 'tmp' / 'elsewhere' / 'x', roots=prone, excluded=admitted) is not None


def test_a_durable_key_never_lands_under_the_aged_out_scratch_prefix() -> None:
    """A remote's lifecycle rule deletes scratch/ after a while; a durable result there would vanish silently."""
    with pytest.raises(ArtefactRefused, match='the prefix a remote ages out'):
        check_key(f'{SCRATCH_PREFIX}/vendor/abc.tar.gz')
    check_key('vendor/scratch/abc.tar.gz')  # PLANTED CONTROL: only the FIRST segment is the aged-out prefix


def test_check_lists_the_remote_through_the_rendered_config(tmp_path: Path) -> None:
    tree, reach, ran = _repo(tmp_path), _reaching(tmp_path), []
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'results').write_text('secret_access_key = "s3cr3t"\n', encoding='utf-8')

    def run(argv: list[str], **_kw: object) -> subprocess.CompletedProcess[str]:
        ran.append(argv)
        return subprocess.CompletedProcess(argv, 0, 'dir-a\ndir-b\n', '')

    said = storage.check('results', repo=tree, to=tmp_path / 'conf' / 'rclone.conf', declared=reach, run=run,
                         rclone=('rclone',))  # fmt: skip
    assert ran == [
        ['rclone', '--config', str(tmp_path / 'conf' / 'rclone.conf'), *storage.CHECK_BOUNDS, 'lsd', 'results:']
    ]
    assert '--retries' in storage.CHECK_BOUNDS  # bounded: a refused key answers in seconds, never a hung terminal
    assert said.startswith('results: reached (2 top-level')
    assert 's3cr3t' not in said


def test_check_refuses_an_unreached_remote_and_a_failed_listing(tmp_path: Path) -> None:
    """PLANTED CONTROL: a remote this machine does not reach, and an rclone refusal, are both refused by name."""
    tree, reach = _repo(tmp_path), _reaching(tmp_path)
    (tmp_path / 'secrets').mkdir()
    (tmp_path / 'secrets' / 'results').write_text('secret_access_key = "s3cr3t"\n', encoding='utf-8')
    with pytest.raises(StorageError, match='not a remote this machine reaches'):
        storage.check('other', repo=tree, to=tmp_path / 'c.conf', declared=reach, rclone=('rclone',))
    refused = subprocess.CompletedProcess([], 1, '', 'AccessDenied: bad key\n')
    with pytest.raises(StorageError, match=r'could not list results: \(exit 1\) AccessDenied'):
        storage.check('results', repo=tree, to=tmp_path / 'c.conf', declared=reach, rclone=('rclone',),
                      run=lambda *_a, **_k: refused)  # fmt: skip
