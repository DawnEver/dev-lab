"""THE MEMBER INDEX: a record's catalogue is validated for the one queried archive; a selection is bounded.

Ported from the 2026-10-15 artefact-member-index work.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from dev_lab.dev import artefactindex
from dev_lab.dev.artefactindex import MemberFact, StoredOutputs
from dev_lab.dev.artefactstores import ArtefactRefused, Ref

PACK_LIMITS = {'max_members': 100, 'max_index_bytes': 65536, 'max_path_bytes': 4096}


def _catalogue_record() -> tuple[dict[str, Any], Ref]:
    ref = Ref('folder', 'lab/archive.tar.gz', 42, 'a' * 64)
    member = MemberFact('dir/é.bin', 0, hashlib.sha256(b'').hexdigest())
    return {'artefacts': [ref.manifest()], 'artefact_indexes': StoredOutputs(ref, (member,)).index()}, ref


@pytest.mark.parametrize(
    'fault',
    [
        'unindexed',
        'duplicate_ref',
        'ref_bytes',
        'bool_ref',
        'foreign_sha',
        'schema',
        'type',
        'bool_bytes',
        'negative_bytes',
        'sha',
        'path',
        'duplicate',
        'extra',
    ],
)
def test_catalogue_refuses_mutated_record_index(fault: str) -> None:
    record, ref = _catalogue_record()
    index = record['artefact_indexes'][ref.sha256]
    member = index['members'][0]
    if fault == 'unindexed':
        record.pop('artefact_indexes')
    if fault == 'duplicate_ref':
        record['artefacts'].append(ref.manifest())
    if fault == 'foreign_sha':
        record['artefact_indexes'] = {'b' * 64: index}
    if fault == 'duplicate':
        index['members'].append(dict(member))
    changes = {
        'ref_bytes': (record['artefacts'][0], 'bytes', 43),
        'bool_ref': (record['artefacts'][0], 'bytes', True),
        'schema': (index, 'schema', 'other'),
        'type': (member, 'type', 'symlink'),
        'bool_bytes': (member, 'logical_bytes', False),
        'negative_bytes': (member, 'logical_bytes', -1),
        'sha': (member, 'sha256', 'bad'),
        'path': (member, 'path', '../escape'),
        'extra': (member, 'role', 'guessed'),
    }
    if fault in changes:
        target, key, value = changes[fault]
        target[key] = value
    with pytest.raises(ArtefactRefused, match='catalogue'):
        artefactindex.catalogue(record, ref, **PACK_LIMITS)


def test_catalogue_budget_and_selection_boundaries() -> None:
    record, ref = _catalogue_record()
    members = artefactindex.catalogue(record, ref, **PACK_LIMITS)  # PLANTED CONTROL: the unmutated record reads
    size = len(json.dumps(record['artefact_indexes'], sort_keys=True, ensure_ascii=True).encode())
    assert artefactindex.catalogue(record, ref, **dict(PACK_LIMITS, max_index_bytes=size)) == members
    with pytest.raises(ArtefactRefused, match='catalogue'):
        artefactindex.catalogue(record, ref, **dict(PACK_LIMITS, max_index_bytes=size - 1))
    limits = {'max_path_bytes': 4096, 'case_sensitive': True}
    assert artefactindex.select_members(members, [], max_entries=0, max_bytes=0, **limits) == ()
    assert artefactindex.select_members(members, ['dir/é.bin'], max_entries=3, max_bytes=0, **limits) == members
    for requested in (['absent'], ['dir/é.bin', 'dir/é.bin']):
        with pytest.raises(ArtefactRefused, match='selection'):
            artefactindex.select_members(members, requested, max_entries=3, max_bytes=0, **limits)
    with pytest.raises(ArtefactRefused, match='selection'):
        artefactindex.select_members(members, ['dir/é.bin'], max_entries=2, max_bytes=0, **limits)


@pytest.mark.parametrize(('paths', 'sensitive'), [(['A/x', 'a/y'], False), (['a', 'a/b'], True), (['A', 'a/b'], False)])
def test_selection_rejects_case_and_file_directory_collisions(paths: list[str], *, sensitive: bool) -> None:
    members = tuple(MemberFact(path, 0, 'a' * 64) for path in paths)
    with pytest.raises(ArtefactRefused, match='selection'):
        artefactindex.select_members(
            members, paths, max_entries=10, max_bytes=0, max_path_bytes=4096, case_sensitive=sensitive
        )


@pytest.mark.parametrize(
    ('key', 'value'),
    [('max_entries', True), ('max_bytes', False), ('max_entries', -1), ('max_bytes', 1.0), ('case_sensitive', 1)],
)
def test_selection_requires_exact_budget_and_case_types(key: str, value: object) -> None:
    limits: dict[str, Any] = {'max_entries': 0, 'max_bytes': 0, 'case_sensitive': True, 'max_path_bytes': 4096}
    limits[key] = value
    with pytest.raises(ArtefactRefused, match='selection'):
        artefactindex.select_members((), [], **limits)


@pytest.mark.parametrize(
    'member',
    [
        MemberFact('a', -1, '0' * 64),
        MemberFact('a', logical_bytes=False, sha256='0' * 64),
        MemberFact('a', 0, 'invalid'),
        MemberFact('../a', 0, '0' * 64),
    ],
)
def test_selection_refuses_constructed_invalid_member_facts(member: MemberFact) -> None:
    with pytest.raises(ArtefactRefused, match='selection'):
        artefactindex.select_members(
            (member,), [member.path], max_entries=10, max_bytes=0, max_path_bytes=4096, case_sensitive=True
        )


def test_catalogue_does_not_validate_other_archives_or_claim_materialization() -> None:
    record, ref = _catalogue_record()
    record['artefacts'].append({'unrelated': 'not validated'})
    record['artefact_indexes']['b' * 64] = {'foreign': 'not queried'}
    assert len(artefactindex.catalogue(record, ref, **PACK_LIMITS)) == 1
    separate = tuple(MemberFact(path, 0, 'a' * 64) for path in ('A/x', 'a/y'))
    selected = artefactindex.select_members(
        separate, ['A/x', 'a/y'], max_entries=5, max_bytes=0, max_path_bytes=4096, case_sensitive=True
    )
    assert selected == separate


def test_catalogue_refuses_lone_surrogate_member_path() -> None:
    record, ref = _catalogue_record()
    record['artefact_indexes'][ref.sha256]['members'][0]['path'] = '\ud800'
    with pytest.raises(ArtefactRefused, match='catalogue'):
        artefactindex.catalogue(record, ref, **PACK_LIMITS)
