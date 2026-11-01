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
from _forge_state import StateForge
from lab_commons.hpc.testcells import TestCell
from lab_commons.outcomes import Cell, Conclusion, Status

from dev_lab.dev import verify, workstationverdict
from dev_lab.dev.forgerecords import Attachment
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.producer import PRODUCING_VAR, ProducerExit
from dev_lab.dev.workstationverdict import ContentKey, Facts, Found, posting_refusal

SHA, OLD = 'a' * 40, 'c' * 40
TREE, OTHER_TREE = 't' * 40, 'u' * 40
ENV = 'env-now'
SERVE = {'repos': ['optimi-lab'], 'parts': 'every'}
CLEAN = Facts(part='base@windows', full=True, declared='', revoked='', dirt=(), pushed=True, stale='')


def test_the_declared_clean_full_run_on_a_pushed_tree_may_post() -> None:
    assert posting_refusal(CLEAN) is None


@pytest.mark.parametrize(
    ('planted', 'named'),
    [
        ({'declared': 'this box does not serve optimi-lab'}, 'does not serve'),
        ({'revoked': 'run-x said PASS; a re-run said FAIL'}, 'revoked'),
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


def test_an_unreadable_revocation_list_refuses_the_post(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """FAIL CLOSED: a box whose revocation cannot be read is not allowed to post."""
    monkeypatch.setattr(workstationverdict, 'forge_from_remote', lambda _root: type('F', (), {'repo': 'optimi-lab'}))
    monkeypatch.setattr(workstationverdict, 'section', lambda _name: SERVE)
    monkeypatch.setattr(workstationverdict, 'present_here', lambda _root: frozenset({'windows'}))
    monkeypatch.setattr(workstationverdict, 'status_paths', lambda _root: ())
    monkeypatch.setattr(workstationverdict, 'pushed', lambda _root: True)
    monkeypatch.setattr(workstationverdict, 'lock_freshness', lambda _root: None)
    monkeypatch.setattr(workstationverdict, 'this_machine', lambda: 'DUIPEZZTZ')

    def unreadable(_client: object) -> dict[str, str]:
        down = 'forge down'
        raise OSError(down)

    monkeypatch.setattr(workstationverdict, 'revoked', unreadable)
    refused = workstationverdict.workstation_refusal(tmp_path, 'base@windows', full=True, client=StateForge())
    assert refused is not None
    assert 'revocation list could not be read' in refused
    monkeypatch.setattr(workstationverdict, 'revoked', lambda _client: {})
    assert workstationverdict.workstation_refusal(tmp_path, 'base@windows', full=True, client=StateForge()) is None


def _record(sha: str, *, env: str = ENV, scope: str = 'full', workstation: str = '', status: str = 'ok') -> dict:
    record = {
        'sha': sha,
        'platform': 'base@windows',
        'scope': scope,
        'req': 'r1',
        'cells': {'t::a': TestCell(Cell(Status(status))).to_plain()},
        'flaky': [],
        'handed': {},
        'env': env,
    }
    return {**record, 'workstation': workstation} if workstation else record


def _store(monkeypatch: pytest.MonkeyPatch, records: dict[str, dict], trees: dict[str, str]) -> dict[str, bytes]:
    """Plant the run-records store (name -> record) and the local sha -> tree map; returns url -> bytes."""
    blobs = {f'u/{name}': gzip.compress(json.dumps(one).encode('utf-8')) for name, one in records.items()}
    listed = tuple(Attachment(index, name, f'u/{name}') for index, name in enumerate(records))
    monkeypatch.setattr(workstationverdict, 'listing', lambda _client: listed)
    monkeypatch.setattr(workstationverdict, 'trees_of', lambda _root, shas: {s: trees[s] for s in shas if s in trees})
    return blobs


def test_a_record_of_the_same_tree_env_and_part_is_a_hit_and_nothing_else_is(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The content key: a different tree, a stale env key or a selection record is never a hit."""
    key = ContentKey(TREE, ENV, 'base@windows')
    planted = {
        f'run-{OLD}-base@windows-r0.json.gz': _record(OLD),  # PLANTED: another tree
        f'run-{SHA}-base@windows-r1.json.gz': _record(SHA, env='env-stale'),  # PLANTED: a stale env key
        f'run-{SHA}-base@windows-r2.json.gz': _record(SHA, scope='incremental'),  # PLANTED: a selection
        f'run-{SHA}-base-r3.json.gz': {**_record(SHA), 'platform': 'base'},  # PLANTED: another part
    }
    blobs = _store(monkeypatch, planted, {OLD: OTHER_TREE, SHA: TREE})
    assert workstationverdict.lookup(tmp_path, StateForge(), key, download=blobs.__getitem__) is None
    hit = f'run-{OLD}-base@windows-r4-0123456789abcdef.json.gz'  # another commit, the SAME tree: still a hit
    blobs = _store(monkeypatch, {**planted, hit: _record(OLD)}, {OLD: TREE, SHA: TREE})
    found = workstationverdict.lookup(tmp_path, StateForge(), key, download=blobs.__getitem__)
    assert found is not None
    assert found.attachment.name == hit


def _found(workstation: str = 'DUIPEZZTZ', status: str = 'ok') -> Found:
    name = f'run-{OLD}-base@windows-r1.json.gz'
    return Found(Attachment(1, name, f'u/{name}'), _record(OLD, workstation=workstation, status=status))


def test_a_hit_is_cited_through_the_status_door_naming_its_record() -> None:
    forge = StateForge()
    line = workstationverdict.cite(forge, SHA, _found())
    (status,) = status_list(forge, SHA)
    assert (status.context, status.state, status.url) == (
        'tests/base@windows',
        'success',
        'u/' + _found().attachment.name,
    )
    assert status.description == 'scope=full ran=1 hands=-', 'a settled part, read as one'
    assert 'CITED' in line
    assert 'DUIPEZZTZ' in line


def test_the_spot_check_samples_only_another_boxs_workstation_records() -> None:
    """The rule: a hit on ANOTHER box's workstation record is re-run when a fresh draw < SPOT_CHECK_FRACTION."""
    low, high = (lambda: 0.0), (lambda: 0.99)
    assert workstationverdict.spot_checked(_found(), me='forge-host', draw=low)
    assert not workstationverdict.spot_checked(_found(), me='forge-host', draw=high)
    assert not workstationverdict.spot_checked(_found(workstation=''), me='forge-host', draw=low), 'a producer record'
    assert not workstationverdict.spot_checked(_found(), me='DUIPEZZTZ', draw=low), 'never its own record'


def test_a_spot_check_mismatch_revokes_the_box_and_an_agreement_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: dict[str, bytes] = {}
    monkeypatch.setattr(workstationverdict, 'read_named', lambda _client, name: stored.get(name))
    monkeypatch.setattr(workstationverdict, 'replace_named', lambda _client, name, data: stored.__setitem__(name, data))
    agrees = workstationverdict.after_run(StateForge(), _found(), Conclusion.PASS)
    assert 'agrees' in agrees
    assert workstationverdict.revoked(StateForge()) == {}
    said = workstationverdict.after_run(StateForge(), _found(), Conclusion.FAIL)
    assert 'REVOKED workstation DUIPEZZTZ' in said
    assert 'said PASS; a re-run said FAIL' in workstationverdict.revoked(StateForge())['DUIPEZZTZ']


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
