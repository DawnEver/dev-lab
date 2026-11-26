"""TAG-DELETE: an agent deletes an origin tag only when the commit it names is contained in integration or the trunk.

Real git (a bare ``origin`` and a clone, the real leased ``push --delete``). The evidence is what ``origin`` holds
afterwards. PLANTED CONTROL: a tag naming a commit nothing declared contains is refused and survives, beside the
contained one that goes; every deletion is recorded (name + sha) before its push.
"""

from __future__ import annotations

from pathlib import Path

from _branch_repos import advance, clone_pair
from _forge_fake import git_out, run_git

from dev_lab.dev._branch_tags import CONTAINED_TAG_DOOR, TAG_EVENT, delete_contained_tags
from dev_lab.dev.branchprune import retired
from dev_lab.dev.forge import fetch_origin
from dev_lab.dev.hooks import DENY_RULES, rules_by_id


def _tag(work: Path, name: str, sha: str, *, annotated: bool = False) -> None:
    extra = ['-a', '-m', name] if annotated else []
    run_git(work, '-c', 'user.name=t', '-c', 'user.email=t@t', 'tag', *extra, name, sha)
    run_git(work, 'push', '-q', '--no-verify', 'origin', f'refs/tags/{name}')


def _on_origin(work: Path, tag: str) -> bool:
    return bool(git_out(work, 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}'))


def test_a_contained_tag_is_recorded_then_deleted_and_an_uncontained_one_survives(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    held = advance(work, 'integrate/main', 'i.txt', 'i\n')
    stray = advance(work, 'lane/x', 'x.txt', 'x\n')
    _tag(work, 'v1', held, annotated=True)
    _tag(work, 'stray', stray)
    run_git(work, 'push', '-q', '--no-verify', 'origin', '--delete', 'lane/x')
    said: list[str] = []
    code = delete_contained_tags(work, ['v1', 'stray'], fetch=fetch_origin, say=said.append)
    assert code == 1, 'the uncontained tag fails the call'
    assert not _on_origin(work, 'v1')
    assert _on_origin(work, 'stray'), 'PLANTED CONTROL: a tag naming uncontained work is never deleted'
    record = next(line for line in said if TAG_EVENT in line)
    assert '"v1"' in record
    assert held in record
    assert any('stray' in line and 'kept' in line for line in said)


def test_a_missing_tag_is_named(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    said: list[str] = []
    assert delete_contained_tags(work, ['nope'], fetch=fetch_origin, say=said.append) == 1
    assert any('nope' in line and 'origin holds no such tag' in line for line in said)


def test_the_raw_delete_refusal_names_the_tag_door() -> None:
    assert CONTAINED_TAG_DOOR.removeprefix('python ') in rules_by_id(DENY_RULES)['PUSH-REMOTE-DELETE'].remedy


def test_an_unlanded_tag_goes_only_on_the_users_words_and_its_record_lists_what_it_drops(tmp_path: Path) -> None:
    """Every non-version tag is cleaned (user ruling 2026-11-26): an unlanded one on the user's words, recorded.

    PLANTED CONTROL: unapproved, the tag stays and the refusal names the approved door; approved, it goes and the
    record carries the tag's sha and every unlanded commit it drops, so each can be recreated.
    """
    _, work = clone_pair(tmp_path)
    advance(work, 'integrate/main', 'i.txt', 'i\n')
    first = advance(work, 'lane/x', 'x.txt', 'x\n')
    second = advance(work, 'lane/x', 'y.txt', 'y\n')
    _tag(work, 'stray', second)
    run_git(work, 'push', '-q', '--no-verify', 'origin', '--delete', 'lane/x')
    said: list[str] = []
    assert delete_contained_tags(work, ['stray'], fetch=fetch_origin, say=said.append) == 1
    assert _on_origin(work, 'stray')
    assert any('--approved' in line for line in said), said
    said.clear()
    code = delete_contained_tags(work, ['stray'], fetch=fetch_origin, say=said.append, approved='clean every tag')
    assert code == 0, said
    assert not _on_origin(work, 'stray')
    record = next(line for line in said if TAG_EVENT in line)
    assert second in record
    assert first in record
    assert 'clean every tag' in record


def test_the_cli_admits_approved_words_on_a_tag() -> None:
    assert retired(['tag', 'stray', '--approved', 'clean it']) == ''
    assert retired(['delete', 'lane/x', '--approved', 'clean it']), 'PLANTED CONTROL: still retired on delete'
