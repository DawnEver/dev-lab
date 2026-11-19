"""A failure fingerprint: a test id plus the subjects its failure names (finding D13, 2026-11-16).

PLANTED CONTROLS: a base red naming A against a head red on the same test naming {A, B} is refused naming B; the
same subjects, and a subject that disappeared, are admitted -- over the pure judgement and over the forge merge's
reading of real (planted) run records.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable

from dev_lab.dev.failprint import Fingerprints, new_subjects, refusal, subject_lines, subjects_of
from dev_lab.dev.forgemerge import hidden_reds
from dev_lab.dev.forgestatus import CommitStatus, fingerprints_at

_NODE = 'tests/test_arch_module_size_alarm.py::test_the_debt_is_exactly_the_modules_that_are_over_the_band'
_HEAD, _TIP = 'a' * 40, 'b' * 40


def test_subject_lines_read_back_through_pytests_gutter() -> None:
    text = 'past the band\n' + subject_lines(['src/b.py', 'src/a.py', 'src/a.py'])
    gutter = '\n'.join(f'E   {line}' for line in text.splitlines())
    assert subjects_of(gutter) == subjects_of(text) == frozenset({'src/a.py', 'src/b.py'})
    assert subjects_of('AssertionError: no subject line here') == frozenset()


def test_a_new_subject_under_an_inherited_red_is_refused_naming_only_it() -> None:
    new = new_subjects({'tests/base': {_NODE: frozenset({'A', 'B'})}}, {'tests/base': {_NODE: frozenset({'A'})}})
    assert new == {('tests/base', _NODE): frozenset({'B'})}
    said = refusal(new)
    assert said is not None
    assert ': B)' in said
    assert 'fix each one' in said


def test_the_same_subjects_and_a_disappeared_one_are_admitted() -> None:
    base = {'tests/base': {_NODE: frozenset({'A', 'B'})}}
    assert new_subjects({'tests/base': {_NODE: frozenset({'A', 'B'})}}, base) == {}
    assert new_subjects({'tests/base': {_NODE: frozenset({'A'})}}, base) == {}
    assert refusal({}) is None


def test_pass_to_fail_is_not_judged_here() -> None:
    """A node red only on the head is the other wait's, so a fingerprint never double-counts it."""
    assert new_subjects({'tests/base': {_NODE: frozenset({'A'})}}, {'tests/base': {}}) == {}


class _Forge:
    """The calls the merge's fingerprint reading makes: a branch tip, each sha's statuses, each record."""

    backend = 'gitea'
    repo = '/api/v1/repos/o/r'

    def __init__(self, subjects: dict[str, set[str]]) -> None:
        self._subjects = subjects

    def call(self, method: str, path: str) -> object:
        assert method == 'GET'
        if path.endswith('/branches/integrate/main'):
            return {'commit': {'id': _TIP}}
        sha = path.rsplit('/', 1)[1]
        url = f'https://forge.example.org/attachments/{sha}.json.gz'
        return [{'id': 1, 'context': 'tests/base', 'status': 'failure', 'description': 'fail', 'target_url': url}]

    def download(self, url: str) -> bytes:
        sha = url.rsplit('/', 1)[1].removesuffix('.json.gz')
        why = 'past the band\n' + subject_lines(self._subjects[sha])
        cell = {'status': 'rejected', 'evidence': 'observed', 'reason': {'kind': 'assertion', 'text': why}}
        return gzip.compress(json.dumps({'cells': {_NODE: cell}}).encode('utf-8'))


def _read(subjects: dict[str, set[str]]) -> Callable[[str], Fingerprints]:
    return lambda ref: fingerprints_at(_Forge(subjects), ref)  # type: ignore[arg-type]


_RED = [CommitStatus('tests/base', 'failure', 'fail', '')]


def test_the_forge_merge_refuses_a_new_subject_against_the_integration_tip() -> None:
    said = hidden_reds(_read({_HEAD: {'A', 'B'}, _TIP: {'A'}}), _HEAD, 'integrate/main', _RED)
    assert said is not None
    assert 'B' in said


def test_the_forge_merge_admits_the_same_and_fewer_subjects() -> None:
    assert hidden_reds(_read({_HEAD: {'A'}, _TIP: {'A'}}), _HEAD, 'integrate/main', _RED) is None
    assert hidden_reds(_read({_HEAD: set(), _TIP: {'A'}}), _HEAD, 'integrate/main', _RED) is None


def test_a_green_head_reads_no_record() -> None:
    green = [CommitStatus('tests/base', 'success', 'pass', '')]
    assert hidden_reds(_read({}), _HEAD, 'integrate/main', green) is None
