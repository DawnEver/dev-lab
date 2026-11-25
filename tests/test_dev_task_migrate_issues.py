"""A MIGRATED TASK GETS ITS IDENTITY: the one-time migration opens each open task's ``task:<slug>`` issue, once.

A task's identity is the forge issue labeled ``task:<slug>`` (user ruling 2026-11-25, R9). A task opened through the
door gets it at open; a task moved from a retired store had none, so :func:`dev_lab.dev.taskmigrate.migrate` opens
it and records ``issue: <url>`` in the ledger's TASK.md. The forge is a fake: no test reaches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _task_ledger import on_branch, plant_ledger
from lab_commons.home import part

from dev_lab.dev import taskledger
from dev_lab.dev._forge_records import Issue
from dev_lab.dev._task_io import ForgeIssues
from dev_lab.dev.taskmigrate import migrate

_DAY = '2026-11-25'
_HELD = 'https://forge.example/t/tasks/issues/9'


class _Forge:
    def __init__(self) -> None:
        self.opened: list[tuple[str, str]] = []

    def open(self, slug: str, goal: str) -> str:
        self.opened.append((slug, goal))
        return f'https://forge.example/t/tasks/issues/{len(self.opened)}'

    def close(self, url: str) -> None:
        del url


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
                       'GIT_COMMITTER_EMAIL': 't@x'}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    root = plant_ledger()
    assert str(root).startswith(str(part('repos'))), 'the ledger is the isolated machine home'
    return root


def _checkout(tmp_path: Path) -> Path:
    checkout = on_branch(tmp_path / 'repo', 'pr/a/x')
    old = checkout.joinpath(*taskledger.RETIRED_STORE)
    for slug, head in (
        ('a', '---\ndescription: "build a"\nauthority: z\nstatus: open\n---\n\n# a\n'),
        ('b', f'---\ndescription: "build b"\nauthority: y\nissue: {_HELD}\nstatus: open\n---\n'),
    ):
        (old / slug).mkdir(parents=True)
        (old / slug / 'TASK.md').write_text(head, encoding='utf-8')
    (old / 'archive' / _DAY / 'c').mkdir(parents=True)
    (old / 'archive' / _DAY / 'c' / 'TASK.md').write_text('---\nstatus: closed\n---\n', encoding='utf-8')
    return checkout


def test_migrate_opens_each_open_tasks_issue_once(ledger: Path, tmp_path: Path) -> None:
    checkout, forge, home = _checkout(tmp_path), _Forge(), tmp_path / 'user'
    plan = migrate(checkout, dry_run=True, user_home=home, forge=forge)
    assert 'would open the task:a issue' in plan
    assert 'task:b' not in plan, 'a task that already names its issue keeps it'
    assert 'task:c' not in plan, 'an archived task is closed: no issue is opened for it'
    assert not forge.opened, 'a dry run reaches no forge'
    said = migrate(checkout, user_home=home, forge=forge)
    assert forge.opened == [('a', 'build a')]
    assert 'opened the task:a issue https://forge.example/t/tasks/issues/1' in said
    text = (ledger / 'a' / 'TASK.md').read_text(encoding='utf-8')
    issue = 'issue: https://forge.example/t/tasks/issues/1'
    assert text == f'---\ndescription: "build a"\nauthority: z\nstatus: open\n{issue}\n---\n\n# a\n'
    assert f'issue: {_HELD}' in (ledger / 'b' / 'TASK.md').read_text(encoding='utf-8')
    again = migrate(checkout, user_home=home, forge=forge)
    assert len(forge.opened) == 1, 'a task whose ledger TASK.md names its issue is never given a second'
    assert 'skipped a' in again, 'the issue line the ledger added is no difference from the retired store'


@pytest.mark.usefixtures('ledger')
def test_a_differing_task_md_still_refuses_beside_the_issue_line(tmp_path: Path) -> None:
    checkout, forge, home = _checkout(tmp_path), _Forge(), tmp_path / 'user'
    migrate(checkout, user_home=home, forge=forge)
    store = checkout.joinpath(*taskledger.RETIRED_STORE)
    (store / 'a' / 'TASK.md').write_text('---\ndescription: "other"\nstatus: open\n---\n', encoding='utf-8')
    with pytest.raises(ValueError, match=r'a/TASK\.md \(from .*already in the ledger'):
        migrate(checkout, user_home=home, forge=forge)


class _Client:
    def __init__(self, held: tuple[Issue, ...]) -> None:
        self.held, self.asked = held, []

    def issue_list(self, *, state: str = 'open', limit: int = 30, labels: tuple[str, ...] = ()) -> tuple[Issue, ...]:
        self.asked.append((state, tuple(labels)))
        return self.held


def test_the_forge_identity_reuses_an_open_issue_already_labeled_for_the_task() -> None:
    held = Issue(number=4, title='task: a -- build a', state='open', body='', url=f'{_HELD[:-1]}4', author='m')
    client = _Client((held,))
    assert ForgeIssues(Path(), client=client).open('a', 'build a') == held.url
    assert client.asked == [('open', ('task:a',))], 'the label is the identity: a re-run opens no duplicate'


def test_a_binding_naming_a_live_store_is_kept_while_that_store_is(ledger: Path, tmp_path: Path) -> None:
    """A session bound under the retired mechanism reads its binding until its checkout's store is removed."""
    checkout = _checkout(tmp_path)
    sessions = part('state') / 'sessions'
    sessions.mkdir(parents=True)
    live, gone = sessions / 'live.json', sessions / 'gone.json'
    for record, store in ((live, checkout.joinpath(*taskledger.RETIRED_STORE)), (gone, tmp_path / 'moved' / 'tasks')):
        record.write_text(json.dumps({'session': record.stem, 'ledger': {'path': store.as_posix()}}), encoding='utf-8')
    plan = migrate(checkout, dry_run=True, user_home=tmp_path / 'user', forge=_Forge())
    assert f'would delete binding record {gone.as_posix()}' in plan
    assert f'kept binding record {live.as_posix()}' in plan
    said = migrate(checkout, user_home=tmp_path / 'user', forge=_Forge())
    assert live.exists(), 'its store still holds tasks: a live session on the retired gate reads this binding'
    assert not gone.exists(), 'planted control: a binding whose store is gone is deleted'
    assert f'kept binding record {live.as_posix()}' in said
    assert (ledger / 'a' / 'TASK.md').is_file()
