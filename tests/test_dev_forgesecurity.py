"""SECURITY IS A PER-HEAD FORGE STATUS: one ``tests/security`` per head, and the merge waits for its ``success``.

The scans are :mod:`dev_lab.dev.security`'s (its planted controls are ``tests/test_security.py``); here the
status they earn, the declaration a repo writes, the serve step's choice of heads, and the merge wait. Every
arm has its planted control.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from _branch_repos import commit
from _forge_fake import run_git

from dev_lab.dev import forgesecurity
from dev_lab.dev._deny_reviewstatus_row import REVIEW_STATUS_VIA_DOORS
from dev_lab.dev.forgecli import NOUNS
from dev_lab.dev.forgecontexts import SECURITY_CONTEXT
from dev_lab.dev.forgesecurity import Declaration, DeclarationInvalid, Judgement, declared, judge, security_wait, step
from dev_lab.dev.forgestatus import CommitStatus
from dev_lab.dev.platformparts import parts_of
from dev_lab.dev.security import AdvisoriesUnreachable

#: Assembled from halves so this file plants no hit in any tree scan.
_TOKEN = 'ghp' + '_' + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8'


def _tree(root: Path, files: dict[str, str]) -> list[str]:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    return sorted(files)


def _clean(_pins: object) -> dict[str, tuple[str, ...]]:
    return {}


_LOCK = (
    'version = 1\n\n[[package]]\nname = "idna"\nversion = "3.10"\nsource = { registry = "https://pypi.org/simple" }\n'
)


def test_a_clean_tree_is_success_and_says_what_was_answered(tmp_path: Path) -> None:
    tracked = _tree(tmp_path, {'src/a.py': 'X = 1\n', 'uv.lock': _LOCK})
    found = judge(tmp_path, tracked, Declaration(), lookup=_clean)
    assert found == Judgement('success', 'ruff S, credentials and 1 locked pin(s): nothing found')


def test_a_planted_shell_true_and_token_fail_named_by_line_and_digest_never_by_value(tmp_path: Path) -> None:
    tracked = _tree(
        tmp_path,
        {'src/run.py': 'import subprocess\n\nsubprocess.run(CMD, shell=True)\n', 'conf.toml': f'token = "{_TOKEN}"\n'},
    )
    found = judge(tmp_path, tracked, Declaration(), lookup=_clean)
    assert found.state == 'failure'
    assert 'src/run.py:3 S602' in found.description
    assert 'conf.toml:1: github token: sha256:' in found.description
    assert _TOKEN not in found.description


def test_an_advisory_fails_unless_the_declaration_accepts_it(tmp_path: Path) -> None:
    tracked = _tree(tmp_path, {'uv.lock': _LOCK})

    def vulnerable(_pins: object) -> dict[str, tuple[str, ...]]:
        return {'idna==3.10': ('GHSA-x',)}

    assert (
        judge(tmp_path, tracked, Declaration(), lookup=vulnerable).description == '1 advisory(ies): idna==3.10: GHSA-x'
    )
    accepted = Declaration(accepted={'GHSA-x': 'the path is unused'})
    assert judge(tmp_path, tracked, accepted, lookup=vulnerable).state == 'success'


def test_an_unreachable_database_is_error_never_success(tmp_path: Path) -> None:
    tracked = _tree(tmp_path, {'uv.lock': _LOCK})

    def down(_pins: object) -> dict[str, tuple[str, ...]]:
        msg = 'api.osv.dev gave no answer'
        raise AdvisoriesUnreachable(msg)

    found = judge(tmp_path, tracked, Declaration(), lookup=down)
    assert found.state == 'error'
    assert 'no answer' in found.description


def test_the_declaration_is_differences_with_reasons_and_nothing_else() -> None:
    text = (
        '[tool.dev_lab.security]\nexclude = { attic = "archive" }\nignore = { S311 = "plot colours" }\n'
        'allowed = { "sha256:0123456789ab" = "a fake" }\naccepted = { "GHSA-x" = "unused" }\n'
    )
    found = declared(text)
    assert (dict(found.exclude), dict(found.ignore)) == ({'attic': 'archive'}, {'S311': 'plot colours'})
    assert (dict(found.allowed), dict(found.accepted)) == ({'sha256:0123456789ab': 'a fake'}, {'GHSA-x': 'unused'})
    assert declared('[project]\nname = "x"\n') == Declaration()
    with pytest.raises(DeclarationInvalid, match='keys are'):
        declared('[tool.dev_lab.security]\nskip = { a = "b" }\n')
    with pytest.raises(DeclarationInvalid, match='non-empty'):
        declared('[tool.dev_lab.security]\nignore = { S311 = "" }\n')


def _status(context: str, state: str, description: str = '') -> CommitStatus:
    return CommitStatus(context, state, description, '', 1)


def test_the_merge_waits_until_the_latest_security_status_is_success() -> None:
    assert security_wait(()) == f'{SECURITY_CONTEXT} is not yet judged'
    for state in ('failure', 'error', 'pending'):
        assert security_wait((_status(SECURITY_CONTEXT, state, 'why'),)) == f'{SECURITY_CONTEXT} is {state}: why'
    assert security_wait((_status(SECURITY_CONTEXT, 'success'),)) is None


def test_the_security_status_is_never_a_part() -> None:
    parts, problems = parts_of((_status(SECURITY_CONTEXT, 'failure', '1 ruff S: a.py:1'),))
    assert (parts, problems) == ({}, ())


def _step(monkeypatch: pytest.MonkeyPatch, posted: dict[str, list[CommitStatus]], pulls: list) -> list:
    """Run the step against a fake forge; the declaration at integration accepts one advisory."""
    git = {
        ('show', 'origin/integrate/main:pyproject.toml'): b'[tool.dev_lab.security]\naccepted = { G = "unused" }\n',
        ('rev-parse', 'origin/integrate/main'): b'i' * 40 + b'\n',
    }
    monkeypatch.setattr(forgesecurity, 'load_policy', lambda _root: SimpleNamespace(integration='integrate/main'))
    monkeypatch.setattr(forgesecurity, '_git', lambda _root, *argv: git[argv])
    monkeypatch.setattr(forgesecurity, 'pr_list', lambda _client: tuple(pulls))
    monkeypatch.setattr(forgesecurity, 'status_list', lambda _client, sha: tuple(posted.get(sha, ())))

    def post(_client: object, sha: str, *, context: str, state: str, description: str) -> None:
        posted.setdefault(sha, []).append(_status(context, state, description))

    monkeypatch.setattr(forgesecurity, 'status_post', post)
    judged: list = []

    def fake(_root: Path, head: str, declaration: Declaration) -> Judgement:
        judged.append((head, dict(declaration.accepted)))
        return Judgement('success', 'nothing found')

    said: list[str] = []
    step(Path(), object(), say=said.append, judged=fake)
    return judged


def test_the_step_judges_each_unjudged_open_head_and_the_integration_head_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """PLANTED controls: a draft, a PR into another base and a settled head are not judged; an error is."""
    pull = SimpleNamespace(number=1, base='integrate/main', draft=False, head_sha='a' * 40)
    draft = SimpleNamespace(number=2, base='integrate/main', draft=True, head_sha='b' * 40)
    other = SimpleNamespace(number=3, base='main', draft=False, head_sha='c' * 40)
    errored = SimpleNamespace(number=4, base='integrate/main', draft=False, head_sha='d' * 40)
    posted: dict[str, list[CommitStatus]] = {'d' * 40: [_status(SECURITY_CONTEXT, 'error', 'osv down')]}
    judged = _step(monkeypatch, posted, [pull, draft, other, errored])
    assert [head for head, _ in judged] == ['a' * 40, 'd' * 40, 'i' * 40]
    assert all(accepted == {'G': 'unused'} for _, accepted in judged), 'read from integration, never the head'
    assert _step(monkeypatch, posted, [pull, draft, other, errored]) == []


def test_a_head_is_judged_from_its_own_tracked_tree(tmp_path: Path) -> None:
    """The real export: ``git archive`` of the head, untracked files never judged."""
    run_git(tmp_path, 'init', '-q')
    head = commit(tmp_path, 'a.py', 'import subprocess\n\nsubprocess.run(CMD, shell=True)\n')
    (tmp_path / 'scratch.py').write_text('import pickle\n\npickle.loads(B)\n', encoding='utf-8')
    found = forgesecurity._judge_head(tmp_path, head, Declaration())
    assert found.state == 'failure'
    assert 'a.py:3 S602' in found.description
    assert 'scratch.py' not in found.description


_BASE_TOML = b'[project]\nname = "x"\n'
_HEAD_TOML = b'[tool.dev_lab.security]\nignore = { S311 = "seeded study samples" }\n'


def _fake_forge(monkeypatch: pytest.MonkeyPatch, head_toml: bytes) -> tuple[dict, list]:
    """One open PR #7 at head ``h``*40 into integration; the head's pyproject is *head_toml*."""
    head = 'h' * 40
    git = {
        ('show', 'origin/integrate/main:pyproject.toml'): _BASE_TOML,
        ('show', f'{head}:pyproject.toml'): head_toml,
        ('rev-parse', 'origin/integrate/main'): b'i' * 40 + b'\n',
    }
    pull = SimpleNamespace(number=7, base='integrate/main', draft=False, head_sha=head)
    posted: dict[str, list[CommitStatus]] = {}
    comments: list = []
    monkeypatch.setattr(forgesecurity, 'load_policy', lambda _root: SimpleNamespace(integration='integrate/main'))
    monkeypatch.setattr(forgesecurity, '_git', lambda _root, *argv: git[argv])
    monkeypatch.setattr(forgesecurity, 'pr_list', lambda _client: (pull,))
    monkeypatch.setattr(forgesecurity, 'status_list', lambda _client, sha: tuple(reversed(posted.get(sha, ()))))

    def post(_client: object, sha: str, *, context: str, state: str, description: str, **_url: str) -> None:
        posted.setdefault(sha, []).append(_status(context, state, description))

    def upsert(_client: object, number: int, *, kind: object, key: str, text: str) -> tuple[str, object]:
        comments.append((number, kind, key, text))
        return 'created', SimpleNamespace(url='c/1', body=text)

    monkeypatch.setattr(forgesecurity, 'status_post', post)
    monkeypatch.setattr(forgesecurity, 'comment_upsert', upsert)
    return posted, comments


def _s311_only(_root: Path, _head: str, declaration: Declaration) -> Judgement:
    """A head whose one finding is an S311 the head's own table ignores."""
    if 'S311' in declaration.ignore:
        return Judgement('success', 'nothing found')
    return Judgement('failure', '1 ruff S: src/a.py:3 S311')


def test_a_head_whose_own_new_exemptions_cover_its_findings_fails_naming_the_release_door(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PLANTED control: the same findings with the table unchanged fail without naming the door."""
    posted, _ = _fake_forge(monkeypatch, _HEAD_TOML)
    step(Path(), object(), say=lambda _line: None, judged=_s311_only)
    (status,) = posted['h' * 40]
    assert status.state == 'failure'
    assert 'covered by the head' in status.description
    assert 'forge security release 7' in status.description
    assert 'S311' in status.description
    posted, _ = _fake_forge(monkeypatch, _BASE_TOML)
    step(Path(), object(), say=lambda _line: None, judged=_s311_only)
    (status,) = posted['h' * 40]
    assert status.state == 'failure'
    assert 'release' not in status.description


def test_the_release_door_posts_success_with_its_reason_and_the_delta(monkeypatch: pytest.MonkeyPatch) -> None:
    posted, comments = _fake_forge(monkeypatch, _HEAD_TOML)
    said = forgesecurity.release(Path(), object(), 7, 'the integrator accepts seeded samples', host='box',
                                 judged=_s311_only)  # fmt: skip
    (status,) = posted['h' * 40]
    assert (status.context, status.state) == (SECURITY_CONTEXT, 'success')
    assert 'released by box' in status.description
    ((number, _, key, text),) = comments
    assert (number, key) == (7, 'h' * 40)
    assert 'the integrator accepts seeded samples' in text
    assert '+ignore.S311' in text
    assert said.endswith('tests/security success')


@pytest.mark.parametrize(
    ('head_toml', 'why', 'judged', 'refusal'),
    [
        (_HEAD_TOML, 'meh', _s311_only, 'reason'),
        (_BASE_TOML, 'a reason long enough', _s311_only, 'does not change'),
        (_HEAD_TOML, 'a reason long enough', lambda *_: Judgement('failure', '1 ruff S: b.py:1 S602'), 'S602'),
    ],
)
def test_the_release_door_refuses_without_a_reason_an_unchanged_table_or_findings_left(
    monkeypatch: pytest.MonkeyPatch, head_toml: bytes, why: str, judged: object, refusal: str
) -> None:
    """PLANTED control: the release test above passes the same door."""
    posted, comments = _fake_forge(monkeypatch, head_toml)
    with pytest.raises(forgesecurity.ReleaseRefused, match=refusal):
        forgesecurity.release(Path(), object(), 7, why, host='box', judged=judged)
    assert (posted, comments) == ({}, [])


def test_the_release_is_the_forge_security_verb(monkeypatch: pytest.MonkeyPatch) -> None:

    assert NOUNS['security'] is forgesecurity.main
    posted, _ = _fake_forge(monkeypatch, _HEAD_TOML)
    monkeypatch.setattr(forgesecurity, '_judge_head', _s311_only)
    monkeypatch.setattr(forgesecurity, 'this_machine', lambda: 'box')
    assert forgesecurity.main(['release', '7', '--why', 'short'], cwd=Path(), client=object()) == 2
    assert forgesecurity.main(['release', '7', '--why', 'seeded samples only'], cwd=Path(), client=object()) == 0
    assert posted['h' * 40][-1].state == 'success'


def test_a_raw_status_post_on_tests_security_is_refused_to_agents() -> None:
    """PLANTED control: the release door is permitted."""
    pattern = re.compile(REVIEW_STATUS_VIA_DOORS['pattern'])
    assert pattern.search('python -m dev_lab.dev.forge status post abc --context tests/security --state success')
    assert not pattern.search('python -m dev_lab.dev.forge security release 7 --why "seeded samples only"')
