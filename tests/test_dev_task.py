"""THE TASK DOOR (user rulings 2026-11-23): the one writer of the machine's task ledger, its grammar and authority.

conftest gives each test its own machine home (``LAB_COMMONS_HOME``), so the ledger planted here is
``<tmp>/repos/tasks`` -- never the machine's. The forge is a fake: no test reaches the network.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _task_ledger import on_branch, plant_ledger
from lab_commons.home import part

from dev_lab.dev import ledgerguard, task, taskauthority, taskjournal, taskledger
from dev_lab.dev._deny_ledger_row import LEDGER_WRITES_THROUGH_ITS_DOOR as ROW
from dev_lab.dev.taskmigrate import RETIRED_AUTHORITY, migrate

_DAY = '2026-11-23'


class _Forge:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.closed: list[str] = []

    def open(self, slug: str, goal: str) -> str:
        del goal
        self.opened.append(slug)
        return f'https://forge.example/t/tasks/issues/{len(self.opened)}'

    def close(self, url: str) -> None:
        self.closed.append(url)


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> Path:
    for key, value in {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
                       'GIT_COMMITTER_EMAIL': 't@x'}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    root = plant_ledger()
    assert str(root).startswith(str(part('repos'))), 'the ledger is the isolated machine home'
    return root


def _grant(root: Path, verb: str, slug: str) -> None:
    payload = json.dumps({'prompt': f'/task {verb} {slug}', 'session_id': 's'})
    assert taskauthority.main(['hook'], stdin=io.StringIO(payload)) == 0
    assert any(e['event'] == 'granted' and e['slug'] == slug for e in taskauthority.events(root))


def _open(root: Path, slug: str = 'toolchain') -> _Forge:
    forge = _Forge()
    _grant(root, 'open', slug)
    task.open_task(slug, 'build the door', forge=forge, date=_DAY)
    return forge


def _log(root: Path) -> list[str]:
    done = subprocess.run(
        [shutil.which('git') or 'git', '-C', str(root), 'log', '--format=%s'],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.splitlines()


def test_open_needs_the_users_grant_and_spends_it_once(ledger: Path) -> None:
    """PLANTED CONTROL: no grant, no task; the grant opens exactly one, then is spent."""
    with pytest.raises(taskauthority.AuthorityRefused, match='Door: the user types `/task open toolchain`'):
        task.open_task('toolchain', 'build the door', forge=_Forge())
    assert not (ledger / 'toolchain').exists()
    forge = _open(ledger)
    head = (ledger / 'toolchain' / 'TASK.md').read_text(encoding='utf-8')
    found = task.read('toolchain')
    assert found is not None
    assert found.authority in head
    assert forge.opened == ['toolchain']
    assert f'opened: build the door (authority {found.authority})' in (ledger / 'toolchain' / 'JOURNAL.md').read_text()
    assert _log(ledger) == ['chore(tasks): open toolchain']
    assert taskauthority.problem(ledger, 'toolchain', found.authority) is None
    assert taskauthority.problem(ledger, 'toolchain', 'forged')[0] == 'error'
    with pytest.raises(task.TaskRefused, match='exists'):
        task.open_task('toolchain', 'again', forge=_Forge())


def test_a_prompt_that_merely_mentions_the_command_grants_nothing(ledger: Path) -> None:
    for prompt in ('please /task open x', 'task open x', '/task opened x'):
        assert taskauthority.grant_from_prompt(ledger, prompt) is None
    code = taskauthority.request(ledger, 'open', 'x', 'goal')
    assert taskauthority.grant_from_prompt(ledger, 'approve 000000') is None, 'planted: an unknown code'
    grant = taskauthority.grant_from_prompt(ledger, f'approve {code}')
    assert grant is not None
    assert (grant['verb'], grant['slug']) == ('open', 'x')
    assert taskauthority.grant_from_prompt(ledger, f'approve {code}') is None, 'a code approves once'
    with pytest.raises(taskauthority.AuthorityRefused):
        taskauthority.consume(ledger, 'close', 'x')  # exactly one verb
    assert taskauthority.consume(ledger, 'open', 'x') == grant['id']
    with pytest.raises(taskauthority.AuthorityRefused):
        taskauthority.consume(ledger, 'open', 'x')


def test_a_grant_expires(ledger: Path) -> None:
    taskauthority.grant_from_prompt(ledger, '/task open x', now=0.0)
    with pytest.raises(taskauthority.AuthorityRefused):
        taskauthority.consume(ledger, 'open', 'x', now=taskauthority.TTL_S + 1.0)


def test_appends_mint_the_next_id_and_commit(ledger: Path, tmp_path: Path) -> None:
    _open(ledger)
    assert task.append('toolchain', 'decide', 'use A', date=_DAY) == f'- {_DAY} D1: use A'
    assert task.append('toolchain', 'decide', 'use B', date=_DAY) == f'- {_DAY} D2: use B'
    assert task.append('toolchain', 'open-item', 'port', date=_DAY) == f'- {_DAY} O1 open: port'
    assert task.append('toolchain', 'close-item', 'done', item=1, date=_DAY) == f'- {_DAY} O1 closed: done'
    with pytest.raises(task.TaskRefused, match='not an open item'):
        task.append('toolchain', 'close-item', 'again', item=1)
    for bad in ('two\nlines', '\u4e2d\u6587'):
        with pytest.raises(task.TaskRefused):
            task.append('toolchain', 'log', bad)
    assert len(_log(ledger)) == 5
    work = on_branch(tmp_path / 'work', 'pr/toolchain/door')
    assert task.current(work) == 'toolchain'
    assert task.main(['log', 'from the branch'], cwd=work) == 0
    assert task.current(on_branch(tmp_path / 'off', 'main')) is None


_UNION = (
    f'- {_DAY} opened: g (authority a)\n- {_DAY} D1: mine\n- {_DAY} O1 open: mine\n'
    f'- {_DAY} D1: theirs\n- {_DAY} O1 open: theirs\n'
)


def _union(ledger: Path) -> None:
    (ledger / 'toolchain' / 'JOURNAL.md').write_text(_UNION, encoding='utf-8')


def test_a_union_merged_journal_is_refused_naming_the_renumbering_amend(ledger: Path, tmp_path: Path) -> None:
    _open(ledger)
    _union(ledger)
    journal = taskjournal.scan(_UNION)
    assert journal.repeats == (('D1', 4), ('O1', 5))
    assert journal.items[0].text == 'mine'
    with pytest.raises(taskjournal.RepeatedId) as refused:
        task.read('toolchain')
    assert 'D1 again at line 4' in str(refused.value)
    assert 'Door: python -m dev_lab.dev.task amend --line 4' in str(refused.value)
    assert 'D2' in str(refused.value)
    work = on_branch(tmp_path / 'work', 'pr/toolchain/x')
    assert task.current(work) == 'toolchain', 'the tolerant read resolves, so the remedy can run'
    with pytest.raises(task.TaskRefused, match='next free id'):
        task.amend('toolchain', 4, f'- {_DAY} D7: theirs', reason='dup')  # planted: not the next free id
    with pytest.raises(task.TaskRefused):
        task.amend('toolchain', 2, f'- {_DAY} D2: mine', reason='dup')  # planted: line 2 is no repeat
    task.amend('toolchain', 4, f'- {_DAY} D2: theirs', reason='duplicate D1 after a union merge')
    task.amend('toolchain', 5, f'- {_DAY} O2 open: theirs', reason='duplicate O1 after a union merge')
    found = task.read('toolchain')
    assert found is not None
    assert [d[0] for d in found.journal.decisions] == [1, 2]


def test_close_validates_everything_before_the_first_write(ledger: Path, tmp_path: Path) -> None:
    forge = _open(ledger)
    task.append('toolchain', 'decide', 'use A')
    task.append('toolchain', 'open-item', 'port')
    checkout = on_branch(tmp_path / 'repo', 'main')
    before = (ledger / 'toolchain' / 'JOURNAL.md').read_text(encoding='utf-8')
    with pytest.raises(task.TaskRefused, match='O1 still open'):
        task.close('toolchain', cwd=checkout, forge=forge)
    task.append('toolchain', 'close-item', 'done', item=1)
    with pytest.raises(task.TaskRefused, match='D1 not distilled'):
        task.close('toolchain', cwd=checkout, forge=forge)
    with pytest.raises(taskauthority.AuthorityRefused):
        task.close('toolchain', cwd=checkout, journal_only=[1], forge=forge)
    assert forge.closed == []
    assert before in (ledger / 'toolchain' / 'JOURNAL.md').read_text(encoding='utf-8')
    (checkout / '.claude' / 'memory').mkdir(parents=True)
    (checkout / '.claude' / 'memory' / 'm.md').write_text('from tasks/toolchain/JOURNAL.md#D1\n', encoding='utf-8')
    _grant(ledger, 'close', 'toolchain')
    dest = task.close('toolchain', 'done', cwd=checkout, forge=forge, date=_DAY)
    assert dest == ledger / 'archive' / _DAY / 'toolchain'
    assert not (ledger / 'toolchain').exists()
    assert 'status: closed' in (dest / 'TASK.md').read_text(encoding='utf-8')
    assert forge.closed
    assert _log(ledger)[0] == 'chore(tasks): close toolchain'
    assert task.read('toolchain') is None
    assert task.main(['list'], cwd=checkout) == 0
    assert task.main(['show', 'toolchain'], cwd=checkout) == 0


def test_archive_is_a_reserved_slug(ledger: Path) -> None:
    del ledger
    with pytest.raises(task.TaskRefused, match='never "archive"'):
        task.open_task('archive', 'x', forge=_Forge())


def _store(checkout: Path) -> Path:
    return checkout.joinpath(*taskledger.RETIRED_STORE)


def test_migrate_moves_a_retired_store_once(ledger: Path, tmp_path: Path) -> None:
    checkout = on_branch(tmp_path / 'repo', 'pr/a/x')
    old = _store(checkout)
    (old / 'a').mkdir(parents=True)
    (old / 'a' / 'TASK.md').write_text('---\nauthority: z\nstatus: open\n---\n', encoding='utf-8')
    (old / 'archive' / _DAY / 'b').mkdir(parents=True)
    (old / 'archive' / _DAY / 'b' / 'TASK.md').write_text('---\nstatus: closed\n---\n', encoding='utf-8')
    (old / '.bindings').mkdir()
    (old / '.bindings' / 's.json').write_text('{}', encoding='utf-8')
    home = tmp_path / 'user'
    rem = home.joinpath(*RETIRED_AUTHORITY)
    rem.mkdir(parents=True)
    key = hashlib.sha256(str(checkout.resolve()).encode()).hexdigest()[:16]
    (rem / f'{key}.jsonl').write_text('{"event":"granted","id":"g1","verb":"open","slug":"a","at":1}\n', 'utf-8')
    sessions = part('state') / 'sessions'
    sessions.mkdir(parents=True)
    (sessions / 'old.json').write_text('{}', encoding='utf-8')
    with pytest.raises(taskledger.LedgerUnresolvedError, match=r'Door: python -m dev_lab\.dev\.task migrate'):
        taskledger.task_of(checkout)
    plan = migrate(checkout, dry_run=True, user_home=home)
    assert 'would copy a' in plan
    assert f'would copy archive/{_DAY}/b' in plan
    assert 'nothing was written' in plan
    assert not (ledger / 'a').exists()
    assert (sessions / 'old.json').exists()
    assert not taskauthority.events(ledger)
    said = migrate(checkout, user_home=home)
    assert (ledger / 'a' / 'TASK.md').is_file()
    assert not (ledger / '.bindings').exists()
    assert not (sessions / 'old.json').exists()
    assert taskauthority.events(ledger)[0]['id'] == 'g1'
    assert 'rm -r .claude' in said
    assert old.exists(), 'the checkout tree is never deleted'
    assert 'skipped a' in migrate(checkout, user_home=home), 'byte-identical: skipped'
    (old / 'a' / 'TASK.md').write_text('---\nstatus: closed\n---\n', encoding='utf-8')
    (old / 'c').mkdir()
    (old / 'c' / 'TASK.md').write_text('---\n---\n', encoding='utf-8')
    with pytest.raises(task.TaskRefused, match=r'a/TASK\.md \(from .*already in the ledger'):
        migrate(checkout, user_home=home)
    assert not (ledger / 'c').exists(), 'a differing non-journal file refuses the WHOLE run before any write'


def test_migrate_union_merges_journals_across_checkouts(ledger: Path, tmp_path: Path) -> None:
    one, two = on_branch(tmp_path / 'one', 'pr/a/x'), on_branch(tmp_path / 'two', 'pr/a/y')
    for checkout, lines in ((one, '- D1 shared\n- O1 one\n'), (two, '- D1 shared\n- O2 two\n')):
        (_store(checkout) / 'a').mkdir(parents=True)
        (_store(checkout) / 'a' / 'TASK.md').write_text('---\nstatus: open\n---\n', encoding='utf-8')
        (_store(checkout) / 'a' / 'JOURNAL.md').write_text(lines, encoding='utf-8')
    home = tmp_path / 'user'
    plan = migrate(one, two, dry_run=True, user_home=home)
    assert 'would copy a' in plan
    assert 'would merge a/JOURNAL.md (+1 line)' in plan, 'the second checkout is planned against the first'
    assert not (ledger / 'a').exists()
    migrate(one, two, user_home=home)
    assert (ledger / 'a' / 'JOURNAL.md').read_text(encoding='utf-8') == '- D1 shared\n- O1 one\n- O2 two\n'
    assert 'skipped a' in migrate(one, two, user_home=home), 'a merged journal is a fixed point'


def test_the_ledger_is_written_only_through_its_door(ledger: Path, tmp_path: Path) -> None:
    refused = ledgerguard.refuse_write(ledger / 't' / 'JOURNAL.md')
    assert refused is not None
    assert refused.startswith(f'{ledgerguard.RULE_ID}:')
    assert 'dev_lab.dev.task' in refused
    assert ledgerguard.refuse_write(tmp_path / 'elsewhere.md') is None, 'planted control: outside the ledger'


def test_the_shell_row_refuses_writes_and_permits_reads() -> None:
    pattern = re.compile(str(ROW['pattern']))
    refuses, permits = ROW['refuses'], ROW['permits']
    assert isinstance(refuses, tuple | list)
    assert isinstance(permits, tuple | list)
    assert all(pattern.search(c) for c in refuses)
    assert not any(pattern.search(c) for c in permits)
