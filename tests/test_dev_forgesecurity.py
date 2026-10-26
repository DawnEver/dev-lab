"""SECURITY IS A PER-HEAD FORGE STATUS: one ``tests/security`` per head, and the merge waits for its ``success``.

The scans are :mod:`dev_lab.dev.security`'s (its planted controls are ``tests/test_security.py``); here the
status they earn, the declaration a repo writes, the serve step's choice of heads, and the merge wait. Every
arm has its planted control.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from _branch_repos import commit
from _forge_fake import run_git

from dev_lab.dev import forgesecurity
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
