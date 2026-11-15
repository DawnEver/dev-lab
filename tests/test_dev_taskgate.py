"""SESSION-COMMITS-UNDER-ITS-TASK: an opt-in repo refuses an agent's commit or push with no open rem task bound."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from dev_lab.dev import taskgate
from dev_lab.dev.sessionprs import SESSION_ENV

AGENT = {SESSION_ENV: '1d9000bd-6cd0-42ab-873f-102cd963e53d'}


def _repo(tmp_path: Path, *, required: bool) -> Path:
    table = '[tool.dev_lab.task]\nrequired = true\n' if required else '[project]\nname = "x"\n'
    (tmp_path / 'pyproject.toml').write_text(table, encoding='utf-8')
    return tmp_path


class _Rem:
    """A fake rem task CLI: answers ``bound``, ``log`` and ``show``; records every call."""

    def __init__(self, bound: str = '(none)', journal: str = '', status: int = 0) -> None:
        self.bound, self.journal, self.status = bound, journal, status
        self.calls: list[list[str]] = []

    def __call__(self, root: Path, args: Sequence[str]) -> tuple[int, str]:
        del root
        self.calls.append(list(args))
        if self.status:
            return self.status, 'boom'
        return 0, {'bound': self.bound, 'show': self.journal}.get(args[0], 'logged')


def test_a_required_repo_refuses_an_agent_with_no_bound_task_and_names_the_door(tmp_path: Path) -> None:
    said = taskgate.refusal(_repo(tmp_path, required=True), env=AGENT, read=_Rem())
    assert said is not None
    assert taskgate.RULE in said
    assert '/rem:task open' in said


def test_a_bound_open_task_passes(tmp_path: Path) -> None:
    """The control: the same required repo with a bound task is not refused."""
    assert taskgate.refusal(_repo(tmp_path, required=True), env=AGENT, read=_Rem(bound='toolchain')) is None


def test_a_repo_that_does_not_declare_it_is_never_judged(tmp_path: Path) -> None:
    rem = _Rem()
    assert taskgate.refusal(_repo(tmp_path, required=False), env=AGENT, read=rem) is None
    assert rem.calls == []  # nothing asked of rem


def test_a_human_commit_is_not_judged(tmp_path: Path) -> None:
    assert taskgate.refusal(_repo(tmp_path, required=True), env={}, read=_Rem()) is None


def test_an_unreadable_ledger_refuses_fail_closed(tmp_path: Path) -> None:
    said = taskgate.refusal(_repo(tmp_path, required=True), env=AGENT, read=_Rem(status=1))
    assert said is not None
    assert 'cannot be read' in said


def test_a_missing_rem_cli_is_an_unreadable_ledger(tmp_path: Path) -> None:
    read = taskgate.reader_for({taskgate.REM_ENV: str(tmp_path / 'absent.js')}, tmp_path)
    said = taskgate.refusal(_repo(tmp_path, required=True), env=AGENT, read=read)
    assert said is not None
    assert taskgate.REM_ENV in said


def test_an_opened_pr_is_appended_through_rems_log_verb_to_the_bound_task(tmp_path: Path) -> None:
    rem = _Rem(bound='toolchain')
    url = 'https://forge.example/o/r/pulls/12'
    taskgate.record(_repo(tmp_path, required=True), 'pr', url, env=AGENT, read=rem)
    assert rem.calls[-1] == ['log', f'pr opened: {url}', '--task', 'toolchain']


def test_nothing_is_recorded_when_the_repo_does_not_require_a_task(tmp_path: Path) -> None:
    rem = _Rem(bound='toolchain')
    assert taskgate.record(_repo(tmp_path, required=False), 'pr', 'u', env=AGENT, read=rem) is None
    assert rem.calls == []


def test_the_task_watches_every_pr_its_journal_records_once(tmp_path: Path) -> None:
    journal = (
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/12\n'
        '- 2026-11-14 progress: issue opened: https://forge.example/o/r/issues/7\n'
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/13\n'
        '- 2026-11-14 progress: pr opened: https://forge.example/o/r/pulls/12\n'
    )
    assert taskgate.task_prs(tmp_path, 'toolchain', _Rem(journal=journal)) == (12, 13)


def test_an_unreadable_journal_raises(tmp_path: Path) -> None:
    with pytest.raises(taskgate.TaskUnreadable):
        taskgate.task_prs(tmp_path, 'toolchain', _Rem(status=1))


class _Forge:
    def pr_view(self, number: int) -> object:
        return type('Pr', (), {'head_sha': f'sha{number}'})()


def test_watch_by_task_watches_the_head_of_every_recorded_pr() -> None:
    journal = 'pr opened: https://forge.example/o/r/pulls/12\npr opened: https://forge.example/o/r/pulls/13\n'
    argv = taskgate.watch_argv(['--task', 'toolchain', '--stream'], _Forge, read=_Rem(journal=journal))
    assert argv == ['sha12', 'sha13', '--stream']


def test_watch_by_a_task_with_no_recorded_pr_refuses() -> None:
    """The control: an empty journal is a named refusal, never a watch of nothing."""
    with pytest.raises(taskgate.TaskUnreadable, match='no open PR head'):
        taskgate.watch_argv(['--task', 'toolchain'], _Forge, read=_Rem())
