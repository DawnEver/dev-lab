"""A DECLARED WORKSTATION POSTS ITS FULL PART (ruling D50-1): every condition refuses when unmet; the key dedupes.

The incident: optimi-lab #124 -- ``tests/base@windows`` read "absent" although the full suite ran clean on a
declared Windows box. Each posting condition carries its own PLANTED CONTROL: an undeclared box, a revoked one, a
dirty tree, an unpushed HEAD, a selection, a stale env key -- each refused -- and the declared clean full run posts.
"""

from __future__ import annotations

import dataclasses
import functools
import gzip
import json
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import git_out, make_repo, run_git
from _forge_state import StateForge
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Conclusion, Reason, Status

from dev_lab.dev import verdictstore, verify, workstationrevoke, workstationverdict
from dev_lab.dev.forgerecords import Attachment
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.producer import PRODUCING_VAR, ProducerExit
from dev_lab.dev.verdictstore import ContentKey, Found
from dev_lab.dev.workstationverdict import Facts, posting_refusal

SHA, OLD = 'a' * 40, 'c' * 40
TREE, OTHER_TREE = 't' * 40, 'u' * 40
ENV = 'env-now'
SERVE = {'repos': ['optimi-lab'], 'parts': 'every'}
STRIKE_FILE = f'workstation-strike-DUIPEZZTZ-{"0" * 32}.json'
CLEAN = Facts(part='base@windows', full=True, declared='', revoked='', dirt=(), pushed=True, stale='')


def test_the_declared_clean_full_run_on_a_pushed_tree_may_post() -> None:
    assert posting_refusal(CLEAN) is None


@pytest.mark.parametrize(
    ('planted', 'named'),
    [
        ({'declared': 'this box does not serve optimi-lab'}, 'does not serve'),
        ({'revoked': 'its contradicted spot checks reached the limit'}, 'revoked'),
        ({'dirt': ('M src/x.py',)}, 'dirty'),
        ({'dirt': None}, 'could not be read'),
        ({'pushed': False}, 'no origin branch'),
        ({'full': False}, 'selection'),
        ({'stale': 'uv.lock moved since the venv synced'}, 'env key is stale'),
    ],
)
def test_every_unmet_condition_refuses_and_names_itself(planted: dict[str, Any], named: str) -> None:
    refused = posting_refusal(dataclasses.replace(CLEAN, **planted))
    assert refused is not None
    assert named in refused


def test_the_declaration_is_the_machine_files_serve_table_and_nothing_else() -> None:
    """``[serve] repos`` names the repo and ``[serve] parts`` claims the part; the box has its needs."""
    ok = workstationverdict.declared_refusal(SERVE, repo='optimi-lab', part='base@windows', present={'windows'})
    assert ok == ''
    assert 'does not serve' in workstationverdict.declared_refusal(
        {}, repo='optimi-lab', part='base', present={'windows'}
    ), 'PLANTED: a box with no [serve] table is no producer -- the default rule never declares a developer box'
    assert 'does not serve' in workstationverdict.declared_refusal(
        SERVE, repo='other-lab', part='base', present={'windows'}
    )
    assert 'does not claim' in workstationverdict.declared_refusal(
        {**SERVE, 'parts': 'needs-a-resource'}, repo='optimi-lab', part='base', present={'windows'}
    )
    assert 'lacks femm' in workstationverdict.declared_refusal(
        SERVE, repo='optimi-lab', part='femm', present={'windows'}
    )


def test_repos_that_is_not_a_list_is_a_refusal_never_a_substring_match() -> None:
    """F-7718516ce1d6: ``repos = "optimi-lab"`` must not declare the box a producer of ``lab``."""
    one = {**SERVE, 'repos': 'optimi-lab'}
    refused = workstationverdict.declared_refusal(one, repo='lab', part='base', present={'windows'})
    assert 'is not a list of repo names' in refused
    refused = workstationverdict.declared_refusal(one, repo='optimi-lab', part='base', present={'windows'})
    assert 'is not a list of repo names' in refused


class Store:
    """The run-records store, in memory: name -> bytes, read through ``listing`` and the client's ``download``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty store, routed into both modules that read it."""
        self.files: dict[str, bytes] = {}
        self.client = StateForge()
        monkeypatch.setattr(self.client, 'download', lambda url: self.files[url], raising=False)
        for module in (verdictstore, workstationrevoke):
            monkeypatch.setattr(module, 'listing', self.listing)
        monkeypatch.setattr(workstationrevoke, 'replace_named', self.replace)
        monkeypatch.setattr(workstationrevoke, 'remove_named', self.remove)

    def listing(self, _client: object) -> tuple[Attachment, ...]:
        return tuple(Attachment(index, name, name) for index, name in enumerate(self.files))

    def replace(self, _client: object, name: str, data: bytes) -> Attachment:
        self.files.pop(name, None)
        self.files[name] = data
        return Attachment(0, name, name)

    def remove(self, _client: object, name: str) -> int:
        return 1 if self.files.pop(name, None) is not None else 0

    def record(self, name: str, record: dict) -> None:
        self.files[name] = gzip.compress(json.dumps(record).encode('utf-8'))


def _declared_box(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workstationverdict, 'forge_from_remote', lambda _root: type('F', (), {'repo': 'optimi-lab'}))
    monkeypatch.setattr(workstationverdict, 'section', lambda _name: SERVE)
    monkeypatch.setattr(workstationverdict, 'present_here', lambda _root: frozenset({'windows'}))
    monkeypatch.setattr(workstationverdict, 'status_paths', lambda _root: ())
    monkeypatch.setattr(workstationverdict, 'pushed', lambda _root: True)
    monkeypatch.setattr(workstationverdict, 'lock_freshness', lambda _root: None)
    monkeypatch.setattr(workstationverdict, 'this_machine', lambda: 'DUIPEZZTZ')


def _refusal(tmp_path: Path, store: Store) -> str:
    return str(workstationverdict.workstation_refusal(tmp_path, 'base@windows', full=True, client=store.client))


def test_an_unreadable_store_refuses_the_post_and_a_malformed_strike_is_ignored_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """FAIL CLOSED on a store that cannot be read; ONE bad strike file never locks out, or revokes, the fleet."""
    _declared_box(monkeypatch)
    store = Store(monkeypatch)
    assert workstationverdict.workstation_refusal(tmp_path, 'base@windows', full=True, client=store.client) is None
    for bad in (b'not json', b'{"a": 1}'):
        store.files[STRIKE_FILE] = bad
        assert workstationverdict.workstation_refusal(tmp_path, 'base', full=True, client=store.client) is None
        assert f'{STRIKE_FILE} is not a strike text -- ignored' in capsys.readouterr().err

    def down(_client: object) -> tuple[Attachment, ...]:
        message = 'forge down'
        raise OSError(message)

    monkeypatch.setattr(workstationrevoke, 'listing', down)
    assert 'revocation list could not be read (forge down)' in _refusal(tmp_path, store)


def test_an_unreadable_declaration_is_a_refusal_not_a_traceback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _declared_box(monkeypatch)
    store = Store(monkeypatch)

    def no_origin(_root: Path) -> object:
        message = 'no origin remote'
        raise OSError(message)

    monkeypatch.setattr(workstationverdict, 'forge_from_remote', no_origin)
    assert 'declaration could not be read (no origin remote)' in _refusal(tmp_path, store)


def _cell(status: str) -> Cell:
    return Cell(Status(status), reason=None if status == 'ok' else Reason('x', 'why'))


def _record(sha: str, *, env: str = ENV, scope: str = 'full', workstation: str = '', status: str = 'ok') -> dict:
    record = {
        'sha': sha,
        'platform': 'base@windows',
        'scope': scope,
        'req': 'r1',
        'cells': {'t::a': TestCell(_cell(status)).to_plain()},
        'flaky': [],
        'handed': {},
        'env': env,
    }
    return {**record, 'workstation': workstation} if workstation else record


KEY = ContentKey(TREE, ENV, 'base@windows')


def _trees(monkeypatch: pytest.MonkeyPatch, trees: dict[str, str]) -> None:
    monkeypatch.setattr(verdictstore, 'trees_of', lambda _root, shas: {s: trees[s] for s in shas if s in trees})


def test_only_a_pass_of_the_same_tree_env_and_part_is_a_hit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The content key: another tree, a stale env key, a selection, another part or a FAIL is never a hit."""
    store = Store(monkeypatch)
    store.record(f'run-{OLD}-base@windows-r0.json.gz', _record(OLD))  # PLANTED: another tree
    store.record(f'run-{SHA}-base@windows-r1.json.gz', _record(SHA, env='env-stale'))  # PLANTED: a stale env key
    store.record(f'run-{SHA}-base@windows-r2.json.gz', _record(SHA, scope='incremental'))  # PLANTED: a selection
    store.record(f'run-{SHA}-base-r3.json.gz', {**_record(SHA), 'platform': 'base'})  # PLANTED: another part
    store.record(f'run-{SHA}-base@windows-r5.json.gz', _record(SHA, status='rejected'))  # PLANTED: a FAIL
    _trees(monkeypatch, {OLD: OTHER_TREE, SHA: TREE})
    assert verdictstore.lookup(tmp_path, store.client, KEY, revoked=()) is None, 'a FAIL is never sticky'
    hit = f'run-{OLD}-base@windows-r4-0123456789abcdef.json.gz'  # another commit, the SAME tree: still a hit
    store.record(hit, _record(OLD))
    _trees(monkeypatch, {OLD: TREE, SHA: TREE})
    found = verdictstore.lookup(tmp_path, store.client, KEY, revoked=())
    assert found is not None
    assert found.attachment.name == hit


def test_a_stored_fail_makes_the_producer_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """F-a6e1540c15a3: a flaky FAIL on a tree is re-run on the next sha of that tree, never cited."""
    store = Store(monkeypatch)
    store.record(f'run-{OLD}-base@windows-r1.json.gz', _record(OLD, status='rejected'))
    _trees(monkeypatch, {OLD: TREE})
    decision = workstationverdict.before_run(tmp_path, SHA, KEY, me='host', client=store.client, draw=lambda: 0.9)
    assert decision == workstationverdict.Decision()
    assert status_list(store.client, SHA) == ()


def test_a_revoked_boxs_earlier_records_are_never_cited(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """F-dc7c4109926e: revocation reaches every record the box already posted."""
    store = Store(monkeypatch)
    store.record(f'run-{OLD}-base@windows-r1.json.gz', _record(OLD, workstation='DUIPEZZTZ'))
    _trees(monkeypatch, {OLD: TREE})
    cited = workstationverdict.before_run(tmp_path, SHA, KEY, me='host', client=store.client, draw=lambda: 0.9)
    assert cited.cited, 'PLANTED CONTROL: before the revocation it is a hit'
    for _ in range(workstationrevoke.STRIKES_TO_REVOKE):
        workstationrevoke.strike(store.client, 'DUIPEZZTZ', 'contradicted')
    after = workstationverdict.before_run(tmp_path, SHA, KEY, me='host', client=store.client, draw=lambda: 0.9)
    assert after == workstationverdict.Decision()


def test_an_unreadable_store_runs_and_says_why(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    store = Store(monkeypatch)
    store.record(f'run-{OLD}-base@windows-r1.json.gz', _record(OLD))

    def git_down(_root: Path, _shas: object) -> dict[str, str]:
        message = 'git cat-file could not read the trees'
        raise OSError(message)

    monkeypatch.setattr(verdictstore, 'trees_of', git_down)
    decision = workstationverdict.before_run(tmp_path, SHA, KEY, me='host', client=store.client)
    assert decision.found is None
    assert 'not read (git cat-file could not read the trees); running' in decision.line


def test_trees_are_read_on_stdin_and_an_unknown_sha_is_left_out(tmp_path: Path) -> None:
    """F-1d9c8a5058ec: no sha on argv; an unknown sha is absent, and git failing RAISES, never reads as none."""
    repo = make_repo(tmp_path, 'https://forge.example.org/o/r.git')
    run_git(repo, 'commit', '-q', '--allow-empty', '-m', 'one')
    head = git_out(repo, 'rev-parse', 'HEAD')
    tree = git_out(repo, 'rev-parse', 'HEAD^{tree}')
    assert verdictstore.trees_of(repo, {head, 'f' * 40}) == {head: tree}
    (tmp_path / 'bare').mkdir()
    with pytest.raises(OSError, match='could not read'):
        verdictstore.trees_of(tmp_path / 'bare', {head})


def _found(workstation: str = 'DUIPEZZTZ') -> Found:
    name = f'run-{OLD}-base@windows-r1.json.gz'
    return Found(Attachment(1, name, f'u/{name}'), _record(OLD, workstation=workstation))


def test_a_hit_is_cited_through_the_status_door_naming_its_record() -> None:
    forge = StateForge()
    line = verdictstore.cite(forge, SHA, _found())
    (status,) = status_list(forge, SHA)
    assert (status.context, status.state, status.url) == (
        'tests/base@windows',
        'success',
        'u/' + _found().attachment.name,
    )
    assert status.description == 'scope=full ran=1 hands=-', 'a settled part, read as one'
    assert 'CITED' in line
    assert 'DUIPEZZTZ' in line


def test_the_spot_check_samples_any_hit_but_its_own() -> None:
    """The rule: a hit not naming this box is re-run when a fresh draw < SPOT_CHECK_FRACTION -- named box or none."""
    low, high = (lambda: 0.0), (lambda: 0.99)
    assert workstationverdict.spot_checked(_found(), me='forge-host', draw=low)
    assert not workstationverdict.spot_checked(_found(), me='forge-host', draw=high)
    assert workstationverdict.spot_checked(_found(workstation=''), me='forge-host', draw=low), 'a record naming no box'
    assert not workstationverdict.spot_checked(_found(), me='DUIPEZZTZ', draw=low), 'never its own record'


def test_one_contradiction_is_a_strike_and_the_limit_revokes(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-7a7698101791: one flaky mismatch does not bar an honest box; the limit does. Each box has its own file."""
    store = Store(monkeypatch)
    assert 'no contradiction' in workstationverdict.after_run(store.client, _found(), Conclusion.PASS)
    assert workstationrevoke.revoked(store.client) == frozenset()
    first = workstationverdict.after_run(store.client, _found(), Conclusion.FAIL)
    assert 'strike 1/2 against DUIPEZZTZ' in first
    assert 'not yet revoked' in first
    assert workstationrevoke.revoked(store.client) == frozenset()
    workstationverdict.after_run(store.client, _found('OTHERBOX'), Conclusion.FAIL)
    second = workstationverdict.after_run(store.client, _found(), Conclusion.FAIL)
    assert 'REVOKED' in second
    assert workstationrevoke.revoked(store.client) == {'DUIPEZZTZ'}
    assert 'names no box' in workstationverdict.after_run(store.client, _found(''), Conclusion.FAIL)


def test_two_strikes_that_interleave_both_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """F-0536583aca76: writer B strikes the box WHILE writer A's upload is in flight; both strikes stand.

    A read-modify-write of one file per box fails this: A read no strikes, B wrote one, A's write replaced it.
    """
    store = Store(monkeypatch)
    plain = store.replace
    interleaved: list[str] = []

    def upload_with_b_in_between(client: object, name: str, data: bytes) -> Attachment:
        if not interleaved:
            interleaved.append('B started')
            interleaved.append(workstationrevoke.strike(store.client, 'DUIPEZZTZ', 'B'))
        return plain(client, name, data)

    monkeypatch.setattr(workstationrevoke, 'replace_named', upload_with_b_in_between)
    said = workstationrevoke.strike(store.client, 'DUIPEZZTZ', 'A')
    assert interleaved, 'PLANTED CONTROL: B really ran inside A'
    assert 'strike 2/2' in said
    assert workstationrevoke.revoked(store.client) == {'DUIPEZZTZ'}


def test_clear_removes_by_name_even_a_malformed_strike_and_fails_when_it_removed_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = Store(monkeypatch)
    monkeypatch.setattr(workstationrevoke, 'client_for', lambda _root: store.client)
    for why in ('one', 'two'):
        workstationrevoke.strike(store.client, 'DUIPEZZTZ', why)
    store.files[STRIKE_FILE] = b'not json'
    assert workstationrevoke.main(['clear', 'DUIPEZZTZ']) == 0
    assert store.files == {}
    assert workstationrevoke.main(['clear', 'DUIPEZZTZ']) == 1, 'nothing removed is no success'
    assert workstationrevoke.main(['clear', 'DUIPEZZTZX']) == 1, 'a mistyped box removes nothing'


def test_box_names_are_injective() -> None:
    """``a-b`` and ``a_b`` are two boxes: one's strikes never count against the other."""
    assert workstationrevoke.box_of('a-b') != workstationrevoke.box_of('a_b')
    assert workstationrevoke.box_of('DUIPEZZTZ') == 'DUIPEZZTZ'


def test_a_revoked_box_is_refused_naming_the_remedy_with_its_real_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-464f9b2fb0f8, F-aea3076e4d37: the refusal names the command to lift it, copy-pasteable."""
    _declared_box(monkeypatch)
    store = Store(monkeypatch)
    for why in ('one', 'two'):
        workstationrevoke.strike(store.client, 'DUIPEZZTZ', why)
    refused = _refusal(tmp_path, store)
    assert 'reached the limit' in refused
    assert 'python -m dev_lab.dev.workstationrevoke clear DUIPEZZTZ,' in refused


def test_lookup_takes_the_newest_record_by_the_forges_id_not_the_listing_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """F-f0df4a8c7ea8: whatever order the forge lists in, the highest id is the newest."""
    store = Store(monkeypatch)
    newer, older = f'run-{OLD}-base@windows-r2.json.gz', f'run-{OLD}-base@windows-r1.json.gz'
    store.record(newer, _record(OLD))
    store.record(older, _record(OLD))
    ids = {newer: 9, older: 1}
    monkeypatch.setattr(
        verdictstore, 'listing', lambda _client: tuple(Attachment(ids[n], n, n) for n in (newer, older))
    )
    _trees(monkeypatch, {OLD: TREE})
    found = verdictstore.lookup(tmp_path, store.client, KEY, revoked=())
    assert found is not None
    assert found.attachment.name == newer


def test_verify_rerun_never_reads_the_store(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """F-fe77aada3432: ``--rerun`` runs the part even when the store holds a PASS of its key; the control cites."""
    _verify_root(monkeypatch, tmp_path)
    monkeypatch.setenv(PRODUCING_VAR, f'tests/base@windows@{SHA}')
    monkeypatch.setattr(verify, 'head_sha', lambda _root: SHA)
    monkeypatch.setattr(verify, 'head_tree', lambda _root: TREE)
    monkeypatch.setattr(verify, 'client_for', lambda _root: StateForge())
    asked: list[object] = []

    def before_run(*_a: object, **_k: object) -> workstationverdict.Decision:
        asked.append(1)
        return workstationverdict.Decision(_found(), cited=True, line='cited')

    monkeypatch.setattr(verify, 'before_run', before_run)
    ran: list[object] = []
    monkeypatch.setattr(verify, '_judge', lambda *_a, **_k: ran.append(1) or (ProducerExit.PASS, []))
    assert verify.main(['--part', 'base@windows']) == ProducerExit.PASS
    assert (asked, ran) == ([1], []), 'PLANTED CONTROL: without --rerun the stored PASS is cited'
    assert verify.main(['--part', 'base@windows', '--rerun']) == ProducerExit.PASS
    assert (asked, ran) == ([1], [1]), '--rerun ran the part and never asked the store'


def _verify_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(PRODUCING_VAR, raising=False)
    monkeypatch.setattr(verify, 'project_root', lambda: tmp_path)
    monkeypatch.setattr(verify, 'box_directory', lambda: tmp_path / 'inflight')
    monkeypatch.setattr(verify, 'cache_path', lambda _root: tmp_path / 'runs.jsonl')
    monkeypatch.setattr(verify, 'lock_freshness', lambda _root: None)
    monkeypatch.setattr(verify, 'part_selection', lambda _root, _part: ())


def test_verify_outside_a_producer_runs_a_declared_workstations_full_part_and_names_the_box(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The exception wired: no producer marker, a declared clean full ``--part`` run is the producer and posts."""
    _verify_root(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'workstation_refusal', lambda _root, _part, *, full: None if full else 'selection')
    monkeypatch.setattr(verify, 'workstation_fields', lambda _root: {'workstation': 'DUIPEZZTZ', 'tree': TREE})
    monkeypatch.setattr(verify, '_stored', lambda *_a, **_k: (None, None))
    seen: list[object] = []

    def judge(*_a: object, post: functools.partial[str] | None, **_k: object) -> tuple:
        seen.append(post.keywords['extra'] if post is not None else None)
        return ProducerExit.PASS, []

    monkeypatch.setattr(verify, '_judge', judge)
    assert verify.main(['--part', 'base@windows']) == ProducerExit.PASS
    assert seen == [{'workstation': 'DUIPEZZTZ', 'tree': TREE}], 'it posts, and its record names the box'


def test_verify_outside_a_producer_refuses_an_undeclared_box_naming_why(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _verify_root(monkeypatch, tmp_path)
    monkeypatch.setattr(verify, 'workstation_refusal', lambda *_a, **_k: 'this box does not serve optimi-lab')
    monkeypatch.setattr(verify, '_judge', lambda *_a, **_k: pytest.fail('an undeclared box ran the full part'))
    assert verify.main(['--part', 'base@windows']) == ProducerExit.USAGE
    err = capsys.readouterr().err
    assert 'push; the forge produces the part' in err
    assert 'does not serve optimi-lab' in err


def test_a_producer_cites_a_stored_hit_and_runs_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """DEDUPE: the producer reads the store by content key first; a hit is posted, never re-run."""
    _verify_root(monkeypatch, tmp_path)
    monkeypatch.setenv(PRODUCING_VAR, f'tests/base@windows@{SHA}')
    monkeypatch.setattr(verify, '_stored', lambda *_a, **_k: (_found(), None))
    monkeypatch.setattr(verify, '_judge', lambda *_a, **_k: pytest.fail('a stored verdict was run again'))
    assert verify.main(['--part', 'base@windows']) == ProducerExit.PASS
