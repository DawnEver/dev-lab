"""REVIEW ROUNDS: findings carried head to head by stable id, closed by a fix or a disposition, blocking while open.

Real git repositories and the stateful fake forge; the review command is a fake printing a findings document.
Every rule has its planted control: the same input one step away from the refused shape passes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from _branch_repos import advance
from _forge_fake import git_out
from test_dev_forgereview import JUDGE, FakeCommand, _forge, _tick, _work

from dev_lab.dev._forgebackends import GITEA, GITHUB
from dev_lab.dev.forgepulls import Marker, comment_upsert, marker
from dev_lab.dev.forgereview import RANGE_FIELD, REVIEW_CONTEXT, Review
from dev_lab.dev.forgereview_findings import Finding, Findings
from dev_lab.dev.forgereview_judge import Claim, Identity, Verdict, adjudication_text, claim, upheld
from dev_lab.dev.forgereview_rounds import (
    SUMMARY_CITES,
    Ledger,
    context_summary,
    ledger_of,
    verdict,
    what_it_does,
)
from dev_lab.dev.forgereview_rounds import (
    advance as advance_round,
)
from dev_lab.dev.forgereview_scope import DISPOSED_FIELD, SUMMARY_FIELD
from dev_lab.dev.forgestatus import status_list

_REVIEW = Review(judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD))


def _finding(fid: str = 'F-000000000001', *, severity: str = 'MEDIUM', security: bool = False,
             file: str = 'x.txt', anchor: str = 'x') -> Finding:  # fmt: skip
    return Finding(fid, severity, security, 'occams-razor', file, anchor, f'{fid} summary', 'Bug')


def _doc(*findings: Finding, **top: object) -> str:
    """A findings-output v3 document of *findings*, one ok reviewer; *top* adds top-level keys."""
    rows = [
        {'id': one.id, 'severity': one.severity, 'security': one.security, 'rule': one.rule, 'file': one.file,
         'anchor': one.anchor, 'summary': one.summary, 'category': one.category, 'status': 'OPEN',
         'suggestion': '', 'detail': '', 'confidence': 'single', 'reviewers': [{'name': 'c', 'provider': 'p'}]}
        for one in findings
    ]  # fmt: skip
    return json.dumps({
        'schema_version': 3, 'range': 'a..b', 'profiles': ['c'],
        'reviewers': [{'name': 'c', 'provider': 'p', 'status': 'ok', 'dropped_findings': 0}], 'findings': rows, **top,
    })  # fmt: skip


def _found(*findings: Finding) -> Findings:
    return Findings(3, 'a..b', ('c',), (), findings)


def _state(forge: object, sha: str) -> tuple[str, str]:
    latest = next(one for one in status_list(forge, sha) if one.context == REVIEW_CONTEXT)
    return latest.state, latest.description


# --- the ledger ----------------------------------------------------------------------------------------


def test_the_ledger_round_trips_through_its_comment_line_and_cannot_close_the_comment() -> None:
    hostile = _finding(anchor='a --> b')
    ledger = Ledger('h' * 40, 2, (hostile,))
    line = ledger.line()
    assert '-->' not in line.removesuffix(' -->'), 'the JSON may not close the HTML comment'
    assert ledger_of(['older', f'text\n{line}']) == ledger
    assert ledger_of(['no ledger here']) is None


def test_the_newest_ledger_wins_and_another_version_is_refused() -> None:
    old, new = Ledger('a' * 40, 1).line(), Ledger('b' * 40, 2).line()
    assert ledger_of([old, new]).round == 2
    with pytest.raises(ValueError, match='version 9'):
        ledger_of([new.replace('"version": 1', '"version": 9')])


# --- blocking -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ('finding', 'state'),
    [
        (_finding(severity='HIGH'), 'failure'),
        (_finding(severity='LOW', security=True), 'failure'),
        (_finding(severity='MEDIUM'), 'success'),  # PLANTED control: below HIGH, not security
        (_finding(severity='LOW'), 'success'),
    ],
)
def test_an_open_high_or_security_finding_is_a_failure(finding: Finding, state: str) -> None:
    assert verdict(Ledger('h' * 40, 1, (finding,)), {}, 7)[0] == state


def test_an_upheld_blocking_finding_no_longer_blocks() -> None:
    high = _finding(severity='HIGH')
    ledger = Ledger('h' * 40, 1, (high,))
    state, said = verdict(ledger, {}, 7)
    assert state == 'failure'
    assert 'forge review dispose 7' in said
    assert verdict(ledger, {high.id: 'a false positive'}, 7)[0] == 'success'


def test_an_upheld_adjudication_counts_only_under_its_own_keyed_marker() -> None:
    """PLANTED control: the same words quoted without the marker, under another id's, or REJECTED, close nothing."""
    ask = Claim('F-1', 'the guard is upstream', Identity('author', 'box', 'S-a'))
    text = adjudication_text(ask, Verdict('F-1', 'false-positive', 'guarded in a.py'), Identity('forge', 'ci', ci=True))
    assert upheld([f'{marker(Marker.ADJUDICATION, "F-1")}\n{text}']) == {
        'F-1': 'false-positive: guarded in a.py (claimed by author@box session S-a)'
    }
    assert upheld([text]) == {}
    assert upheld([f'{marker(Marker.ADJUDICATION, "F-2")}\n{text}']) == {}
    rejected = adjudication_text(ask, Verdict('F-1', 'present', 'not guarded'), Identity('forge', 'ci', ci=True))
    assert upheld([f'{marker(Marker.ADJUDICATION, "F-1")}\n{rejected}']) == {}


# --- rounds ---------------------------------------------------------------------------------------------


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A PR branch adding ``x.txt`` (``x``, ``y``) then rewriting it: (work, first head, second head)."""
    work, _ = _work(tmp_path)
    first = advance(work, 'pr/x', 'x.txt', 'x\ny\n')
    second = advance(work, 'pr/x', 'x.txt', 'y\nz\n')
    return work, first, second


def test_round_two_closes_a_finding_whose_anchor_is_gone_and_keeps_one_whose_anchor_stays(tmp_path: Path) -> None:
    work, first, second = _repo(tmp_path)
    gone, stays = _finding('F-1', anchor='x'), _finding('F-2', anchor='  y ')
    prior = Ledger(first, 1, (gone, stays))
    judged = {'F-1': Verdict('F-1', 'fixed', 'x is gone from x.txt'), 'F-2': Verdict('F-2', 'present', 'y stays')}
    ledger = advance_round(work, second, f'{first}..{second}', prior, _found(), judged=judged)
    assert ledger.round == 2
    assert [one.id for one in ledger.open] == ['F-2']
    assert ledger.closed == (('F-1', 'fixed: x is gone from x.txt'),), 'the evidence is recorded'


def test_every_round_re_judges_a_finding_whose_scenario_the_head_removed(tmp_path: Path) -> None:
    """User ruling 2026-10-31: the round RE-JUDGES, never carries the text over.

    The anchor line STAYS, but the head removed the scenario, and round 2 closes it with the judge's evidence -- no
    dispose.

    PLANTED CONTROL: the same finding judged `present` stays open and blocking.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    high = _finding('F-x', severity='HIGH', file='x.py', anchor='x')
    _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
    after = advance(work, 'pr/x', 'guard.py', 'assert x\n')  # x.py keeps its anchor line; a guard now covers it
    forge.pulls[number]['head']['sha'] = after
    rulings = {'F-x': ('fixed', 'guard.py asserts x before use')}
    command = FakeCommand(_doc(), rulings=rulings)
    _tick(work, forge, command, _REVIEW)
    assert _state(forge, after)[0] == 'success'
    ((asked,),) = command.judged
    assert asked['id'] == 'F-x'
    assert 'fixed: guard.py asserts x before use' in forge.comments[number][-1]['body']
    still = advance(work, 'pr/x', 'other.py', 'o\n')
    forge.pulls[number]['head']['sha'] = still
    _tick(work, forge, FakeCommand(_doc(high), rulings={'F-x': ('present', 'nothing guards x')}), _REVIEW)
    assert _state(forge, still)[0] == 'failure', 're-raised and judged present: it blocks again'


def test_a_later_round_raises_no_new_non_high_finding_on_a_line_it_did_not_add(tmp_path: Path) -> None:
    """No moving goalposts. PLANTED controls: the same MEDIUM on an added line, and a HIGH anywhere, are raised."""
    work, first, second = _repo(tmp_path)
    reviewed = f'{first}..{second}'
    old_line = _finding('F-old', anchor='y')  # y was there before this round
    new_line = _finding('F-new', anchor='z')  # z is what this round added
    high = _finding('F-high', severity='HIGH', anchor='y')
    ledger = advance_round(work, second, reviewed, Ledger(first, 1), _found(old_line, new_line, high), judged={})
    assert [one.id for one in ledger.open] == ['F-new', 'F-high']
    first_round = advance_round(work, second, reviewed, None, _found(old_line), judged={})
    assert [one.id for one in first_round.open] == ['F-old'], 'round 1 reads the whole change'


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


# --- through the forge ----------------------------------------------------------------------------------


def test_a_fix_pushed_after_a_blocking_round_closes_it_and_the_head_succeeds(tmp_path: Path) -> None:
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    high = _finding('F-x', severity='HIGH', file='x.py', anchor='x')
    _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
    assert _state(forge, head)[0] == 'failure'
    fixed = advance(work, 'pr/x', 'x.py', 'fixed\n')
    forge.pulls[number]['head']['sha'] = fixed
    command = FakeCommand(_doc())
    _tick(work, forge, command, _REVIEW)
    state, said = _state(forge, fixed)
    assert (state, 'review round 2' in said) == ('success', True)
    ((argv, _),) = command.ran
    assert argv[-1] == f'{head}..{fixed}', 'round 2 reads only what the branch added since the reviewed head'
    body = forge.comments[number][-1]['body']
    assert '### Closed this round' in body
    assert 'What changed' not in body, 'only round 1 carries the context summary'


def test_a_claim_is_adjudicated_by_the_next_round_and_only_an_upheld_one_unblocks(tmp_path: Path) -> None:
    """The round's judge rules on the pending claim and posts the ruling. PLANTED CONTROL: a rejected claim blocks."""
    for outcome, state in (('false-positive', 'success'), ('present', 'failure')):
        (tmp_path / outcome).mkdir()
        work, head = _work(tmp_path / outcome)
        forge, number = _forge(head)
        high = _finding('F-x', severity='HIGH', anchor='x')
        _tick(work, forge, FakeCommand(_doc(high)), _REVIEW)
        claim(forge, number, 'F-x', 'the guard is upstream', by=Identity('a', 'box', 'S-author'), open_ids=['F-x'])
        assert _state(forge, head)[0] == 'failure', 'a claim moves no status'
        after = advance(work, 'pr/x', 'y.py', 'y = 1\n')  # code: a round runs
        forge.pulls[number]['head']['sha'] = after
        command = FakeCommand(_doc(high), rulings={'F-x': (outcome, 'ruled on the code')})
        _tick(work, forge, command, _REVIEW)
        assert command.judged[0][0]['claim'] == 'the guard is upstream'
        assert _state(forge, after)[0] == state
        (ruling,) = [c['body'] for c in forge.comments[number] if marker(Marker.ADJUDICATION, 'F-x') in c['body']]
        assert 'claimed by a@box session S-author' in ruling


def test_the_comment_opens_with_what_the_pr_does_and_lists_what_was_disposed_earlier(tmp_path: Path) -> None:
    """The engine's summary opens the comment, each claim's cites linked; the ids it dropped are listed.

    It is handed the PR body and the forge's own dispositions ONLY: a commit trailer is the author's, applied
    after the engine returns.
    """
    work, _ = _work(tmp_path)
    trailer = 'fix(x): keep x\n\nReview-Disposed: F-old -- a false positive'
    head = advance(work, 'pr/x', 'x.py', 'x\nw\n', message=trailer)
    forge, number = _forge(head, body='This PR adds x.')
    ask = Claim('F-led', 'up', Identity('author', 'box', 'S-a'))
    ruled = adjudication_text(ask, Verdict('F-led', 'false-positive', 'up'), Identity('forge', 'ci', ci=True))
    comment_upsert(forge, number, kind=Marker.ADJUDICATION, key='F-led', text=ruled)
    memory = '.claude/memory/2026/10/29/x.md'
    summary = {'changes': [{'claim': 'adds x', 'cites': [head, memory]}], 'tests_altered': [], 'resolutions': [],
               'open_items': ['wire y'], 'sources': ['commits']}  # fmt: skip
    seen: list[tuple[str, object]] = []

    def run(argv: list[str], _root: Path) -> str:
        body = Path(argv[argv.index('--pr-body') + 1]).read_text(encoding='utf-8')
        seen.append((body, json.loads(Path(argv[argv.index('--disposed') + 1]).read_text(encoding='utf-8'))))
        return _doc(_finding('F-m', file='x.py', anchor='w'), summary=summary,
                    disposed=[{'id': 'F-led', 'reason': 'up'}])  # fmt: skip

    review = Review(
        judge=JUDGE, command=('reviewer', '--range', RANGE_FIELD, SUMMARY_FIELD, '--disposed', DISPOSED_FIELD)
    )
    _tick(work, forge, run, review)
    ((body, gone),) = seen
    assert body == 'This PR adds x.'
    reason = 'false-positive: up (claimed by author@box session S-a)'
    assert gone == {'disposed': [{'id': 'F-led', 'reason': reason}]}, 'only an upheld claim reaches the engine'
    text = forge.comments[number][-1]['body']
    repo = forge.pulls[number]['html_url'].rsplit('/pulls/', 1)[0]
    commit_link, memory_link = (
        f'[`{head[:12]}`]({repo}/commit/{head})',
        f'[`{memory}`]({repo}/src/commit/{head}/{memory})',
    )
    assert text.removeprefix(marker(Marker.REVIEW, head) + '\n').startswith('### What this PR does\n')
    assert f'- adds x ({commit_link}, {memory_link})' in text
    assert '**Open items**:\n- wire y' in text
    assert '### Disposed earlier\n- `F-led`: up' in text
    assert text.index('What this PR does') < text.index('Review round 1') < text.index('F-m summary')


def _authored(tmp_path: Path, *findings: Finding, names: str) -> tuple[str, str]:
    """Round 1 of a head whose commit trailer disposes of *names*; its ``(state, comment body)``."""
    work, _ = _work(tmp_path)
    head = advance(work, 'pr/x', 'x.py', 'x\nw\n', message=f'fix(x): keep x\n\nReview-Disposed: {names} -- by design')
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_doc(*findings)), _REVIEW)
    return _state(forge, head)[0], forge.comments[number][-1]['body']


def test_an_author_trailer_never_suppresses_a_blocking_finding(tmp_path: Path) -> None:
    """A trailer naming a HIGH finding leaves it open and blocking, and says an upheld claim is needed."""
    state, text = _authored(tmp_path, _finding('F-h', severity='HIGH', file='x.py', anchor='w'), names='F-h')
    assert state == 'failure'
    rows = text.split('### Blocking (open)\n', 1)[1].split('\n\n', 1)[0]
    assert 'F-h summary' in rows
    assert 'the author disposed it (by design); a blocking finding needs an upheld claim' in rows
    assert 'by the author' not in text


def test_an_author_trailer_disposes_of_a_non_blocking_finding_after_the_engine(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same trailer naming a MEDIUM finding lists it as disposed by the author."""
    state, text = _authored(tmp_path, _finding('F-m', file='x.py', anchor='w'), names='F-m')
    assert state == 'success'
    assert '### Disposed earlier (by the author)\n- `F-m` -- by design' in text
    assert '### Open, not blocking' not in text


@pytest.mark.parametrize(('backend', 'file_form'), [(GITEA, 'src/commit'), (GITHUB, 'blob')])
def test_what_it_does_links_its_cites_in_the_backend_form(backend: object, file_form: str) -> None:
    repo, head, sha = 'https://f/o/r', 'b' * 40, 'a' * 40
    summary = {'changes': [{'claim': 'adds x', 'cites': [sha, 'x.py']}]}
    text = what_it_does(summary, repo, head, backend)
    assert f'- adds x ([`{sha[:12]}`]({repo}/commit/{sha}), [`x.py`]({repo}/{file_form}/{head}/x.py))' in text


def test_the_re_judge_reads_the_whole_change_at_the_head_never_the_increment(tmp_path: Path) -> None:
    """#7 round 3: a finding about a file the increment did not touch was judged on the increment alone.

    The round's reviewer reads its increment; the JUDGE of an open finding reads the PR's whole change at the head.
    PLANTED CONTROL: the round's own review command still reads only the increment.
    """
    work, head = _work(tmp_path)
    forge, number = _forge(head)
    _tick(work, forge, FakeCommand(_doc(_finding('F-x', severity='HIGH', file='x.py', anchor='x'))), _REVIEW)
    after = advance(work, 'pr/x', 'y.py', 'y = 1\n')
    forge.pulls[number]['head']['sha'] = after
    seen: list[list[str]] = []
    command = FakeCommand(_doc())

    def run(argv: list[str], root: Path) -> str:
        seen.append(list(argv))
        return command(argv, root)

    _tick(work, forge, run, _REVIEW)
    judged = next(argv for argv in seen if argv[0] == 'judge')
    reviewed = next(argv for argv in seen if argv[0] == 'reviewer')
    base = git_out(work, 'merge-base', 'origin/integrate/main', after)
    assert judged[judged.index('--range') + 1] == f'{base}..{after}'
    assert reviewed[-1] == f'{head}..{after}'
