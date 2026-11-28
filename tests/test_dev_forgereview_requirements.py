"""REVIEW REQUIREMENTS (D226): a repo declares what its advisory review judges a change against.

Every refusal here has its PLANTED CONTROL: the declaration it refuses, made whole, is accepted; the payload it
builds is read at the trusted branch the caller names, never anywhere else.
"""

from __future__ import annotations

import base64
import json
import re
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
    with_unjudged,
)
from dev_lab.dev.forgereview_requirements import (
    DEFAULT_MAX_ARCHITECTURE,
    FAMILY_REQUIREMENTS,
    REQUIREMENT_KINDS,
    requirements_at,
    requirements_refusal,
)
from dev_lab.dev.forgereview_scope import REQUIREMENTS_FIELD
from dev_lab.dev.forgereview_summary import CHECKLIST_TITLE, checklist
from dev_lab.dev.reviewbundle import Bundle

_TRUSTED = 'integrate/main'
_TIP = 'c' * 40  # the trusted branch's commit


class _Forge:
    """One repository as the branch, git-trees and contents APIs answer it: each branch's tip, each commit's files."""

    def __init__(
        self, files: dict[str, dict[str, str]], *, branches: dict[str, str] | None = None, page: int = 0,
        repo: str = '/api/v1/repos/o/r',
    ) -> None:  # fmt: skip
        self.files = files  # {commit: {path: text}}
        self.branches = branches if branches is not None else {_TRUSTED: _TIP}
        self.page = page  # >0: the tree is listed this many entries a page (Gitea's paging); <0: truncated, no page
        self.repo = repo
        self.asked: list[str] = []

    def call(self, method: str, path: str, /) -> object:
        assert method == 'GET'
        self.asked.append(path)
        route, _, query = path.partition('?')
        asked = dict(one.split('=', 1) for one in query.split('&')) if query else {}
        if '/branches/' in route:
            return {'commit': {'id': self.branches[unquote(route.split('/branches/', 1)[1])]}}
        if '/git/trees/' in route:
            return self._tree(route.rsplit('/git/trees/', 1)[1], int(asked.get('page', '1')))
        where = unquote(route.split('/contents/', 1)[1])
        text = self.files.get(asked['ref'], {}).get(where)
        if text is None:
            return {}
        return {'content': base64.b64encode(text.encode()).decode(), 'sha': f'blob-of-{where}'}

    def _tree(self, sha: str, page: int) -> dict[str, Any]:
        rows = [{'path': one, 'type': 'blob', 'size': len(text.encode())} for one, text in self.files[sha].items()]
        if self.page < 0:  # GitHub past its limit: truncated, and no page to read on
            return {'tree': rows[:1], 'truncated': True}
        if not self.page:
            return {'tree': rows, 'truncated': False}
        cut = rows[(page - 1) * self.page : page * self.page]
        return {'tree': cut, 'truncated': page * self.page < len(rows), 'page': page}


def _review(text: str) -> Review:
    return review_from(f'[tool.dev_lab.review]\n{text}\n', 'p')


def _payload(forge: _Forge, review: Review) -> dict[str, Any]:
    required = requirements_at(forge, review, _TRUSTED)
    assert required.unjudged == (), required.unjudged
    return dict(required.payload)


_ARCH = 'requirements = ["principles", "architecture"]\narchitecture = [{globs}]'


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
        # review item 4: a value of the wrong shape is refused naming the form, never read as its letters
        ('requirements = "principles"', "requirements = 'principles' is not a list of non-empty strings: write"),
        ('requirements = ["principles", ""]', 'requirements = ['),
        ('requirements = ["architecture"]\narchitecture = "AGENTS.md"', "architecture = 'AGENTS.md' is not a list"),
        ('requirements = ["architecture"]\narchitecture = [1]', 'architecture = [1] is not a list of non-empty'),
    ],
)
def test_half_a_requirement_an_unknown_kind_or_a_wrong_shape_is_refused_by_name(text: str, said: str) -> None:
    """PLANTED CONTROL: each declaration made whole loads (the test above, and requirements = [] below)."""
    with pytest.raises(ValueError, match=re.escape(said)):
        _review(text)
    assert _review('requirements = []').requirements == ()


@pytest.mark.parametrize('key', ['command', 'synthesis', 'bundle'])
def test_every_declared_method_carries_the_requirements_file(key: str) -> None:
    """Review item 5: every declared command, synthesis and bundle carries ``{requirements}``, whatever is declared.

    The engine refuses ANY call without ``--requirements`` (ai-lab NO_REQUIREMENTS), even one listing none.

    PLANTED CONTROL: the same declaration carrying the field loads; the family commands carry it.
    """
    assert REQUIREMENTS_FIELD in FAMILY_COMMAND
    assert REQUIREMENTS_FIELD in FAMILY_BUNDLE
    argv = '"r", "{bundle}"' if key == 'bundle' else '"r", "{range}"'
    for declared in ('', 'requirements = []\n'):
        with pytest.raises(ValueError, match=re.escape(f'{key} names no {{requirements}}')) as refused:
            _review(f'{declared}{key} = [{argv}]')
        assert 'requirements = []' not in str(refused.value), 'requirements = [] would still be NO_REQUIREMENTS'
    carried = _review(f'{key} = [{argv}, "--requirements", "{{requirements}}"]')
    assert REQUIREMENTS_FIELD in getattr(carried, key)


# --- the payload, read from one snapshot of the trusted branch --------------------------------------------------


def test_the_principles_alone_read_nothing_from_the_forge() -> None:
    forge = _Forge({})
    assert _payload(forge, review_from('', 'p')) == {'principles': True}
    assert forge.asked == []
    assert _payload(forge, _review('requirements = []')) == {}


def test_the_architecture_is_read_at_one_commit_of_the_trusted_branch_never_the_head() -> None:
    """Review item 6: the branch is resolved to a commit ONCE; the tree and every document are read at it.

    PLANTED CONTROL: the head holds a different AGENTS.md; the payload carries the trusted commit's text.
    """
    forge = _Forge({
        _TIP: {'AGENTS.md': 'layers point down\n', 'docs/a.md': 'A\n', 'docs/b.md': 'B\n', 'src/x.py': ''},
        'head-sha': {'AGENTS.md': 'anything goes\n'},
    }, branches={_TRUSTED: _TIP, 'pr/x': 'head-sha'})  # fmt: skip
    payload = _payload(forge, _review(_ARCH.format(globs='"AGENTS.md", "docs/*.md"')))
    assert payload['principles'] is True
    assert payload['architecture'] == [
        {'id': 'arch:AGENTS.md', 'path': 'AGENTS.md', 'blob': 'blob-of-AGENTS.md', 'text': 'layers point down\n'},
        {'id': 'arch:docs/a.md', 'path': 'docs/a.md', 'blob': 'blob-of-docs/a.md', 'text': 'A\n'},
        {'id': 'arch:docs/b.md', 'path': 'docs/b.md', 'blob': 'blob-of-docs/b.md', 'text': 'B\n'},
    ]
    branches = [one for one in forge.asked if '/branches/' in one]
    assert branches == [f'{forge.repo}/branches/integrate/main'], 'the branch is resolved once, by its name'
    reads = [one for one in forge.asked if '/branches/' not in one]
    assert all(_TIP in one for one in reads), reads
    assert not any('head-sha' in one or 'pr/x' in one for one in forge.asked)


def test_a_paged_gitea_tree_is_read_to_its_last_page() -> None:
    """PLANTED CONTROL: the document on page 2 is found; a GitHub tree truncated with no page is refused."""
    files = {f'f{at}.txt': '' for at in range(5)} | {'docs/zz.md': 'Z\n'}
    forge = _Forge({_TIP: files}, page=2)
    assert [row['path'] for row in _payload(forge, _review(_ARCH.format(globs='"docs/*.md"')))['architecture']] == [
        'docs/zz.md'
    ]
    assert sum('/git/trees/' in one for one in forge.asked) == 3
    hub = _Forge({_TIP: files}, page=-1, repo='/repos/o/r')
    required = requirements_at(hub, _review(_ARCH.format(globs='"docs/*.md"')), _TRUSTED)
    assert required.unjudged[0][0] == 'architecture'
    assert 'truncated the tree' in required.unjudged[0][1]


@pytest.mark.parametrize(
    ('globs', 'said'),
    [
        ('"docs/*.md"', "architecture entry 'docs/*.md' matches no file at integrate/main"),
        ('"ARCH.md"', "architecture entry 'ARCH.md' matches no file at integrate/main"),
    ],
)
def test_an_architecture_that_cannot_be_built_degrades_alone_naming_the_fix(globs: str, said: str) -> None:
    """Review item 3: a bad declaration never silently turns off the review; the architecture alone degrades.

    The principles are still judged, and the architecture is listed ``unverified`` with its cause (merge-ready names
    the same, requirements_refusal).

    PLANTED CONTROL: the same declaration over a tree holding the documents builds (above).
    """
    forge = _Forge({_TIP: {'AGENTS.md': 'x\n'}})
    review = _review(_ARCH.format(globs=globs))
    required = requirements_at(forge, review, _TRUSTED)
    assert dict(required.payload) == {'principles': True}
    ((key, why),) = required.unjudged
    assert key == 'architecture'
    assert said in why
    assert 'fix the path in architecture = [...]' in why
    assert requirements_refusal(forge, review, _TRUSTED) == why.removeprefix('not judged: ')
    assert requirements_refusal(forge, _review(_ARCH.format(globs='"AGENTS.md"')), _TRUSTED) is None


def test_documents_past_max_architecture_degrade_naming_the_key_and_every_size_before_any_read() -> None:
    """PLANTED CONTROL: one byte more of cap reads the same documents."""
    forge = _Forge({_TIP: {'a.md': 'x' * 6, 'b.md': 'y' * 5}})
    declared = _ARCH.format(globs='"a.md", "b.md"') + '\nmax_architecture = "{cap} B"'
    required = requirements_at(forge, _review(declared.replace('{cap}', '10')), _TRUSTED)
    assert 'is 11 B, past max_architecture (10 B): a.md 6 B, b.md 5 B' in required.unjudged[0][1]
    assert not any('/contents/' in one for one in forge.asked), 'judged from the tree listing, before any read'
    assert len(_payload(forge, _review(declared.replace('{cap}', '11')))['architecture']) == 2


def test_an_unbuilt_requirement_is_listed_unverified_in_the_review() -> None:
    """The review comment's checklist names it; PLANTED CONTROL: nothing unbuilt changes nothing."""
    text = _doc(('first-principles', 'met', []))
    assert with_unjudged(text, ()) == text
    found = parse_findings(with_unjudged(text, (('architecture', 'not judged: glob matches nothing'),)))
    assert [(row.id, row.verdict, row.evidence) for row in found.requirements] == [
        ('first-principles', 'met', 'first-principles met'),
        ('architecture', 'unverified', 'not judged: glob matches nothing'),
    ]


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
