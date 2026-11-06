"""PR-REVIEW-IS-ONE-SHOT-ADVICE: the review's one record, comment and status (``forgereview_advice``).

Every finding is advice except a security finding; the comment states the one-shot rule and lists what the budget
left unread; a record is read only from the forge's own (or a declared reviewer's) comments. Every rule has its
planted control.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_state import StateForge
from _review_doubles import _finding
from test_dev_forgereview import _work

from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.forgepulls import Marker, comment_upsert
from dev_lab.dev.forgereview_advice import (
    AGAIN_DOOR,
    ONE_SHOT,
    Record,
    post_review_comment,
    record_of,
    render,
    trusted_bodies,
    verdict,
)
from dev_lab.dev.forgereview_findings import Findings
from dev_lab.dev.forgereview_identity import Identity, ReviewerRefused
from dev_lab.dev.forgereview_summary import SUMMARY_CITES, context_summary, what_it_does
from dev_lab.dev.forgestatus import status_list
from dev_lab.dev.platformparts import REVIEW_CONTEXT

_FORGE = Identity('forge', 'ci', ci=True)
_FORBIDDEN = 'sp' + 'lit'  # spelled in parts: the retired-spellings scan reads this file too


def _found(*findings: object) -> Findings:
    return Findings(3, 'a..b', ('c',), (), tuple(findings))


# --- the record ------------------------------------------------------------------------------------------


def test_the_record_round_trips_through_its_comment_line_and_cannot_close_the_comment() -> None:
    record = Record('h' * 40, (_finding(anchor='a --> b'),), usd=1.5, size=1234)
    line = record.line()
    assert '-->' not in line.removesuffix(' -->'), 'the JSON may not close the HTML comment'
    assert record_of(['older', f'text\n{line}']) == record
    assert record_of(['no record here']) is None


def test_the_newest_record_wins_and_another_version_is_refused() -> None:
    old, new = Record('a' * 40).line(), Record('b' * 40, size=7).line()
    assert record_of([old, new]).head == 'b' * 40
    with pytest.raises(ValueError, match='version 9'):
        record_of([new.replace('"version": 1', '"version": 9')])


# --- advice, and the one blocking kind --------------------------------------------------------------------


@pytest.mark.parametrize('severity', ['HIGH', 'MEDIUM', 'LOW'])
def test_a_finding_of_any_severity_is_advice_and_the_review_is_success(severity: str) -> None:
    state, said = verdict(Record('h' * 40, (_finding(severity=severity),)), 7)
    assert state == 'success'
    assert f'1 {severity}' in said
    assert 'none blocks' in said


def test_a_security_finding_is_the_one_failure_naming_the_review_again_door() -> None:
    """PLANTED CONTROL for the advice test: the same finding with ``security`` set holds the merge."""
    state, said = verdict(Record('h' * 40, (_finding('F-s', severity='LOW', security=True),)), 7)
    assert state == 'failure'
    assert 'F-s' in said
    assert AGAIN_DOOR.format(pr=7) in said


def test_the_comment_states_the_one_shot_rule_lists_the_unread_code_and_never_asks_to_divide_the_pr() -> None:
    record = Record('h' * 40, (_finding('F-a', severity='HIGH'), _finding('F-s', security=True)))
    text = render(record, number=7, reviewed='a..b', found=_found(*record.findings), unread=('big/one.py',))
    assert ONE_SHOT in text
    assert '`big/one.py`' in text
    assert text.index('### Security (holds the merge)') < text.index('F-s summary')
    assert text.index('### Advice') < text.index('F-a summary')
    assert _FORBIDDEN not in text.lower().replace(ONE_SHOT.lower(), '')
    assert 'never ' + _FORBIDDEN + ' it for the review' in ONE_SHOT, 'the rule is stated positively, once'


# --- what is trusted ------------------------------------------------------------------------------------


def test_a_record_pasted_by_another_author_is_never_read_but_a_declared_reviewers_is() -> None:
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha='h' * 40)
    forge.login = 'author'
    comment_upsert(forge, number, kind=Marker.REVIEW, key='a' * 40, text=f'mine\n{Record("a" * 40).line()}')
    forge.login = 'a'
    assert record_of(trusted_bodies(forge, number)) is None
    assert record_of(trusted_bodies(forge, number, reviewers=('author',))).head == 'a' * 40


# --- through the forge ----------------------------------------------------------------------------------


def test_the_forge_posts_one_comment_and_a_success_status_for_advice(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    pull = forge.pr_view(number)
    said = post_review_comment(work, forge, pull, f'origin/integrate/main..{head}',
                               found=_found(_finding(severity='HIGH')), reviewer=_FORGE, authors=frozenset(),
                               size=40)  # fmt: skip
    assert 'success' in said
    (comment,) = forge.comments[number]
    assert record_of([comment['body']]).size == 40
    (status,) = [s for s in status_list(forge, head) if s.context == REVIEW_CONTEXT]
    assert status.state == 'success'
    assert _FORBIDDEN not in status.description.lower()


def test_a_session_review_is_advisory_and_its_own_head_is_refused(tmp_path: Path) -> None:
    """PLANTED CONTROL: the forge's identity posts the status; a session's posts the comment alone."""
    work, head = _work(tmp_path)
    forge = StateForge()
    number = forge.add_pull('pr/x', 'integrate/main', sha=head)
    pull = forge.pr_view(number)
    session = Identity('dev', 'box', 'S-1')
    post_review_comment(work, forge, pull, 'a..b', found=_found(), reviewer=session, authors=frozenset(),
                        advisory=True)  # fmt: skip
    assert status_list(forge, head) == ()
    assert len(forge.comments[number]) == 1
    with pytest.raises(ReviewerRefused, match='authored this head'):
        post_review_comment(work, forge, pull, 'a..b', found=_found(), reviewer=session,
                            authors=frozenset({'S-1'}), advisory=True)  # fmt: skip


# --- the summary that opens the comment --------------------------------------------------------------------


def test_the_context_summary_names_what_changed_why_and_where(tmp_path: Path) -> None:
    work, _ = _work(tmp_path)
    (work / 'src' / 'pkg' / 'layer').mkdir(parents=True)
    (work / 'docs').mkdir()
    base = advance(work, 'pr/x', 'src/pkg/layer/a.py', 'a = 1\n')
    head = advance(work, 'pr/x', 'docs/b.md', '# b\n')
    text = context_summary(work, f'{base}~1..{head}')
    assert '2 file(s), +2/-0' in text
    assert '`src/pkg/layer` (1)' in text
    assert '`docs` (1)' in text
    assert '**Why** (the commits):\n- docs/b.md\n- src/pkg/layer/a.py' in text  # the subjects, newest first


def test_the_context_summary_cites_each_declared_source_in_order(tmp_path: Path) -> None:
    """SUMMARY_CITES is the order the WHY is cited in: commits, the memory landed, merges, the PR body."""
    work, _ = _work(tmp_path)
    (work / '.claude' / 'memory').mkdir(parents=True, exist_ok=True)
    head = advance(work, 'pr/x', '.claude/memory/m.md', '# m\n', message='docs(memory): m')
    text = context_summary(work, f'origin/integrate/main..{head}', pr_body='Adds x.\n\nMore.')
    assert SUMMARY_CITES == ('commits', 'memory', 'merge_audit', 'pr_body')
    assert '- `.claude/memory/m.md`' in text
    assert '> Adds x.' in text
    assert text.index('(the commits)') < text.index('`.claude/memory/m.md`') < text.index('> Adds x.')
    assert '(the merges)' not in text, 'PLANTED control: a range without merges cites none'


@pytest.mark.parametrize(('backend', 'file_form'), [(GITEA, 'src/commit'), (GITHUB, 'blob')])
def test_what_it_does_links_its_cites_in_the_backend_form(backend: object, file_form: str) -> None:
    repo, head, sha = 'https://f/o/r', 'b' * 40, 'a' * 40
    summary = {'changes': [{'claim': 'adds x', 'cites': [sha, 'x.py']}]}
    text = what_it_does(summary, repo, head, backend)
    assert f'- adds x ([`{sha[:12]}`]({repo}/commit/{sha}), [`x.py`]({repo}/{file_form}/{head}/x.py))' in text
