"""REVIEW REQUIREMENTS (D226): a repo declares what its advisory review judges a change against.

Every refusal here has its PLANTED CONTROL: the declaration it refuses, made whole, is accepted; the payload it
builds is read at the trusted branch the caller names, never anywhere else.
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import unquote

import pytest

from dev_lab.dev import forgereview_bundle
from dev_lab.dev.forgereview_advice import Record, render, verdict
from dev_lab.dev.forgereview_declared import FAMILY_BUNDLE, FAMILY_COMMAND, Review, review_from
from dev_lab.dev.forgereview_findings import (
    REQUIREMENT_VERDICTS,
    FindingsInvalid,
    Requirement,
    merge_outputs,
    parse_findings,
)
from dev_lab.dev.forgereview_requirements import (
    DEFAULT_MAX_ARCHITECTURE,
    FAMILY_REQUIREMENTS,
    REQUIREMENT_KINDS,
    RequirementsRefused,
    requirements_at,
)
from dev_lab.dev.forgereview_scope import REQUIREMENTS_FIELD
from dev_lab.dev.forgereview_summary import CHECKLIST_TITLE, checklist
from dev_lab.dev.reviewbundle import Bundle
from dev_lab.dev.reviewgate import DeclarationUnread

_TRUSTED = 'integrate/main'


class _Forge:
    """One repository's contents and tree at each ref, as the contents and git-trees APIs answer them."""

    repo = '/api/v1/repos/o/r'

    def __init__(self, files: dict[str, dict[str, str]]) -> None:
        self.files = files  # {ref: {path: text}}
        self.asked: list[str] = []

    def call(self, method: str, path: str, /) -> object:
        assert method == 'GET'
        self.asked.append(path)
        route, _, query = path.partition('?')
        if '/git/trees/' in route:
            ref = unquote(route.rsplit('/git/trees/', 1)[1])
            return {'tree': [{'path': one, 'type': 'blob'} for one in self.files[ref]], 'truncated': False}
        where = unquote(route.split('/contents/', 1)[1])
        ref = dict(one.split('=', 1) for one in query.split('&'))['ref']
        text = self.files.get(ref, {}).get(where)
        if text is None:
            return {}
        return {'content': base64.b64encode(text.encode()).decode(), 'sha': f'blob-of-{where}'}


def _review(text: str) -> Review:
    return review_from(f'[tool.dev_lab.review]\n{text}\n', 'p')


def _payload(forge: _Forge, review: Review) -> dict[str, Any]:
    return requirements_at(forge, review, _TRUSTED)


# --- the declaration -------------------------------------------------------------------------------------------


def test_the_family_requires_the_principles_and_a_repo_may_add_its_architecture() -> None:
    assert REQUIREMENT_KINDS == ('principles', 'architecture')
    family = review_from('', 'p')
    assert (family.requirements, family.architecture, family.max_architecture) == (
        FAMILY_REQUIREMENTS, (), DEFAULT_MAX_ARCHITECTURE,
    )  # fmt: skip
    declared = _review('requirements = ["principles", "architecture"]\narchitecture = ["AGENTS.md", "docs/*.md"]\n'
                       'max_architecture = "50 kB"')  # fmt: skip
    assert declared.requirements == ('principles', 'architecture')
    assert declared.architecture == ('AGENTS.md', 'docs/*.md')
    assert declared.max_architecture == 50_000


@pytest.mark.parametrize(
    ('text', 'said'),
    [
        ('requirements = ["architecture"]', 'no architecture = [<globs>]'),
        ('architecture = ["AGENTS.md"]', 'requirements does not list "architecture"'),
        ('requirements = ["principles", "style"]', "names ['style']"),
        ('requirements = ["principles", "principles"]', "lists ['principles'] twice"),
        ('requirements = []\narchitecture = ["AGENTS.md"]', 'requirements does not list "architecture"'),
        ('max_architecture = 5', 'max_architecture'),
        ('requirement = ["principles"]', 'unknown key'),
    ],
)
def test_half_a_requirement_or_an_unknown_kind_is_refused_by_name(text: str, said: str) -> None:
    """PLANTED CONTROL: each declaration made whole loads (the test above, and requirements = [] below)."""
    with pytest.raises(ValueError, match=said.replace('[', r'\[').replace(']', r'\]')):
        _review(text)
    assert _review('requirements = []').requirements == ()


def test_the_family_commands_hand_the_requirements_and_a_declared_command_must_too() -> None:
    """A custom command that drops ``{requirements}`` while requirements are declared would judge none of them.

    PLANTED CONTROL: the same command declaring no requirements, or carrying the field, loads.
    """
    assert REQUIREMENTS_FIELD in FAMILY_COMMAND
    assert REQUIREMENTS_FIELD in FAMILY_BUNDLE
    with pytest.raises(ValueError, match=r'command names no \{requirements\}'):
        _review('requirements = ["principles"]\ncommand = ["r", "{range}"]')
    with pytest.raises(ValueError, match=r'bundle names no \{requirements\}'):
        _review('requirements = ["principles"]\nbundle = ["r", "{bundle}"]')
    assert _review('command = ["r", "{range}"]').command == ('r', '{range}')
    carried = _review('requirements = ["principles"]\ncommand = ["r", "{range}", "--requirements", "{requirements}"]')
    assert REQUIREMENTS_FIELD in carried.command
    assert _review('requirements = []\ncommand = ["r", "{range}"]').requirements == ()


# --- the payload, read at the trusted branch --------------------------------------------------------------------


def test_the_principles_alone_read_nothing_from_the_forge() -> None:
    forge = _Forge({})
    assert _payload(forge, review_from('', 'p')) == {'principles': True}
    assert forge.asked == []
    assert _payload(forge, _review('requirements = []')) == {}


def test_the_architecture_is_read_at_the_trusted_branch_never_the_head() -> None:
    """PLANTED CONTROL: the head holds a different AGENTS.md; the payload carries the trusted branch's text."""
    forge = _Forge({
        _TRUSTED: {'AGENTS.md': 'layers point down\n', 'docs/a.md': 'A\n', 'docs/b.md': 'B\n', 'src/x.py': ''},
        'pr/x': {'AGENTS.md': 'anything goes\n'},
    })  # fmt: skip
    review = _review('requirements = ["principles", "architecture"]\narchitecture = ["AGENTS.md", "docs/*.md"]')
    payload = _payload(forge, review)
    assert payload['principles'] is True
    assert payload['architecture'] == [
        {'id': 'arch:AGENTS.md', 'path': 'AGENTS.md', 'blob': 'blob-of-AGENTS.md', 'text': 'layers point down\n'},
        {'id': 'arch:docs/a.md', 'path': 'docs/a.md', 'blob': 'blob-of-docs/a.md', 'text': 'A\n'},
        {'id': 'arch:docs/b.md', 'path': 'docs/b.md', 'blob': 'blob-of-docs/b.md', 'text': 'B\n'},
    ]
    assert all('pr/x' not in one for one in forge.asked)


def test_a_glob_matching_nothing_and_an_absent_document_are_refused_by_name() -> None:
    """PLANTED CONTROL: the same declaration over a tree that holds the documents is read (above)."""
    forge = _Forge({_TRUSTED: {'AGENTS.md': 'x\n'}})
    with pytest.raises(RequirementsRefused, match=r"glob 'docs/\*\.md' matches no file at integrate/main"):
        _payload(forge, _review('requirements = ["architecture"]\narchitecture = ["docs/*.md"]'))
    with pytest.raises(DeclarationUnread, match=r'ARCH\.md at integrate/main'):
        _payload(forge, _review('requirements = ["architecture"]\narchitecture = ["ARCH.md"]'))


def test_documents_past_max_architecture_are_refused_naming_the_key_and_every_size() -> None:
    """PLANTED CONTROL: one byte more of cap reads the same documents."""
    forge = _Forge({_TRUSTED: {'a.md': 'x' * 6, 'b.md': 'y' * 5}})
    declared = 'requirements = ["architecture"]\narchitecture = ["a.md", "b.md"]\nmax_architecture = "{cap} B"'
    with pytest.raises(RequirementsRefused, match=r'is 11 B, past max_architecture \(10 B\): a\.md 6 B, b\.md 5 B'):
        _payload(forge, _review(declared.format(cap=10)))
    assert len(_payload(forge, _review(declared.format(cap=11)))['architecture']) == 2


# --- the engine's answers: read, combined across slices, listed, and never a merge condition ---------------------


def _doc(*rows: tuple[str, str, list[str]], security: bool = False) -> str:
    findings = (
        [{
            'id': 'F-0123456789ab', 'severity': 'HIGH', 'security': True, 'rule': 'R', 'file': 'x.py', 'anchor': 'a',
            'summary': 's', 'category': 'Bug', 'status': 'OPEN', 'suggestion': '', 'detail': '', 'confidence': 'one',
            'reviewers': [{'name': 'r', 'provider': 'p'}],
        }]
        if security else []
    )  # fmt: skip
    required = [{'id': key, 'verdict': said, 'cites': cites, 'evidence': f'{key} {said}'} for key, said, cites in rows]
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['r'],
        'reviewers': [{'name': 'r', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': findings,
        **({'requirements': required} if rows else {}),
    })  # fmt: skip


def test_the_verdicts_are_read_and_an_output_without_them_reads_none() -> None:
    """PLANTED CONTROL: an unknown verdict, or cites that are no list, is refused by name."""
    found = parse_findings(_doc(('first-principles', 'met', []), ('arch:AGENTS.md', 'violated', ['x.py:3'])))
    assert found.requirements == (
        Requirement('first-principles', 'met', (), 'first-principles met'),
        Requirement('arch:AGENTS.md', 'violated', ('x.py:3',), 'arch:AGENTS.md violated'),
    )
    assert parse_findings(_doc()).requirements == ()
    with pytest.raises(FindingsInvalid, match=r'requirements\[0\]\.verdict'):
        parse_findings(_doc(('first-principles', 'fine', [])))
    bad = json.loads(_doc(('first-principles', 'met', [])))
    bad['requirements'][0]['cites'] = 'x.py'
    with pytest.raises(FindingsInvalid, match=r'requirements\[0\]\.cites'):
        parse_findings(json.dumps(bad))


@pytest.mark.parametrize(
    ('one', 'other', 'kept'),
    [
        ('untouched', 'met', 'met'),
        ('met', 'unverified', 'unverified'),
        ('unverified', 'amended', 'amended'),
        ('amended', 'violated', 'violated'),
        ('violated', 'untouched', 'violated'),  # PLANTED CONTROL: order of the slices never weakens it
    ],
)
def test_slices_combine_to_the_strongest_verdict_and_every_cite(one: str, other: str, kept: str) -> None:
    assert REQUIREMENT_VERDICTS == ('violated', 'amended', 'unverified', 'met', 'untouched')
    merged = parse_findings(merge_outputs([_doc(('p', one, ['a.py'])), _doc(('p', other, ['b.py', 'a.py']))], 'a..b'))
    assert [(row.id, row.verdict, row.cites) for row in merged.requirements] == [('p', kept, ('a.py', 'b.py'))]
    assert merged.requirements[0].evidence == f'p {kept}'
    assert 'requirements' not in json.loads(merge_outputs([_doc(), _doc()], 'a..b'))


def test_the_checklist_lists_every_verdict_and_says_it_is_advisory() -> None:
    """PLANTED CONTROL: no requirement renders no checklist."""
    text = checklist((Requirement('p', 'met', ()), Requirement('arch:A.md', 'violated', ('x.py',), 'it imports up')))
    assert text.splitlines() == [
        CHECKLIST_TITLE,
        '- [x] `p` **met**',
        '- [ ] `arch:A.md` **violated**: it imports up (`x.py`)',
    ]
    assert 'never a merge condition' in CHECKLIST_TITLE
    assert checklist(()) == ''


def test_a_violated_requirement_is_listed_and_never_changes_the_verdict() -> None:
    """D226: the review stays advisory -- only a security finding requests changes, as before.

    PLANTED CONTROL: the same output with a security finding requests changes on both review bodies.
    """
    violated = parse_findings(_doc(('arch:A.md', 'violated', ['x.py'])))
    bundle = cast('Bundle', SimpleNamespace(head_sha='h' * 40, base_sha='b' * 40))
    judged = forgereview_bundle._rendered(violated, bundle)
    assert judged.event == 'APPROVED'
    assert '`arch:A.md` **violated**' in judged.body
    record = Record('h' * 40, violated.findings)
    assert verdict(record, 1)[0] == 'success'
    assert '`arch:A.md` **violated**' in render(record, number=1, reviewed='a..b', found=violated)
    secured = parse_findings(_doc(('arch:A.md', 'violated', ['x.py']), security=True))
    assert forgereview_bundle._rendered(secured, bundle).event == 'REQUEST_CHANGES'
    assert verdict(Record('h' * 40, secured.findings), 1)[0] == 'failure'
