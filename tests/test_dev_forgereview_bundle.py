"""The bundle review: the runner prepares and points, the judge verifies, reviews and posts a PR review once per head.

PLANTED CONTROLS: a tampered forge diff is refused as REQUEST_CHANGES, a blocking finding is REQUEST_CHANGES, a
head already judged by this login is not judged again, a ``serve`` repo is never judged and a ``judge`` repo is
never served, and a command that fails posts nothing.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev import forgereview_bundle as fb
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev._forgebackends import GITEA
from dev_lab.dev.artefacts import FolderStore, Ref
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_declared import FAMILY_BUNDLE, JUDGE, Review, command_for, review_from
from dev_lab.dev.reviewbundle import BundleRefused

_JUDGED = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "review-bot"\n'
_JUDGE_TOML = '[tool.dev_lab.integrator]\nintegration = "main"\n' + _JUDGED
_RUNTIMES = {'ai_lab': {'python': 'py'}}


def _findings(severity: str | None) -> str:
    rows = [{'name': 'r', 'provider': 'anthropic', 'status': 'ok', 'dropped_findings': 0}]
    found = (
        []
        if severity is None
        else [{
            'id': 'F-0123456789ab', 'severity': severity, 'security': False, 'rule': 'R', 'file': 'kept.py',
            'anchor': 'x', 'summary': 's', 'category': 'Bug', 'status': 'OPEN', 'suggestion': '', 'detail': '',
            'confidence': 'single', 'reviewers': [{'name': 'r', 'provider': 'anthropic'}],
        }]
    )  # fmt: skip
    return json.dumps({'schema_version': 3, 'range': 'a..b', 'profiles': ['r'], 'reviewers': rows, 'findings': found})


@dataclass
class FakeForge:
    """One Gitea repository as the two sides see it: statuses, reviews, files by ref, the PR and its diff."""

    pull: PullRequest
    diff: str
    manifest: str = _JUDGE_TOML
    login: str = 'review-bot'
    poster: str | None = None  # who the runner's status is recorded as: None is Gitea's Actions (null creator)
    statuses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reviews: list[dict[str, Any]] = field(default_factory=list)
    forge: Forge = field(default_factory=lambda: Forge('forge.example.org', 'o', 'r'))
    backend: Any = GITEA
    repo: str = '/api/v1/repos/o/r'

    def pr_view(self, number: int) -> PullRequest:
        assert number == self.pull.number
        return self.pull

    def whoami(self) -> str:
        return self.login

    def pull_diff(self, number: int) -> str:
        assert number == self.pull.number
        return self.diff

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, durable: object = None) -> Any:  # noqa: ANN401
        del durable
        path = path.partition('?')[0]
        return self._post(path, body or {}) if method == 'POST' else self._get(path)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path.endswith('/reviews'):
            self.reviews.append({'user': {'login': self.login}, 'state': body['event'], **body})
            return self.reviews[-1]
        rows = self.statuses.setdefault(path.rsplit('/', 1)[1], [])
        creator = None if self.poster is None else {'login': self.poster}
        rows.append({'id': len(rows) + 1, 'creator': creator, **body})
        return rows[-1]

    def _get(self, path: str) -> Any:  # noqa: ANN401
        manifest = {'content': base64.b64encode(self.manifest.encode()).decode()}
        answers = {
            self.repo: {'default_branch': 'main'},
            f'{self.repo}/contents/pyproject.toml': manifest,
            f'{self.repo}/pulls/{self.pull.number}/reviews': list(self.reviews),
            f'{self.repo}/pulls': [_raw(self.pull)],
            f'{self.repo}/statuses/{self.pull.head_sha}': list(self.statuses.get(self.pull.head_sha, [])),
        }
        return answers[path]


def _raw(pull: PullRequest) -> dict[str, Any]:
    return {
        'number': pull.number, 'title': pull.title, 'state': 'open', 'body': pull.body, 'html_url': pull.url,
        'user': {'login': pull.author}, 'head': {'ref': pull.head, 'sha': pull.head_sha}, 'base': {'ref': pull.base},
        'draft': False, 'labels': [],
    }  # fmt: skip


def _repo(tmp_path: Path) -> tuple[Path, str, str]:
    remote, root = tmp_path / 'remote.git', tmp_path / 'repo'
    run_git(tmp_path, 'init', '-q', '--bare', '-b', 'main', str(remote))
    run_git(tmp_path, 'clone', '-q', str(remote), str(root))
    for key, value in (('user.name', 't'), ('user.email', 't@t')):
        run_git(root, 'config', key, value)
    (root / 'pyproject.toml').write_text(_JUDGE_TOML, encoding='utf-8')
    (root / 'kept.py').write_text('x = 1\n', encoding='utf-8')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'base')
    run_git(root, 'push', '-q', 'origin', 'main')
    base = git_out(root, 'rev-parse', 'HEAD')
    run_git(root, 'checkout', '-q', '-b', 'pr/x')
    (root / 'kept.py').write_text('x = 10\n', encoding='utf-8')
    (root / 'logo.png').write_bytes(b'\x89PNG\x00\x01')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'head')
    return root, base, git_out(root, 'rev-parse', 'HEAD')


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[FakeForge, Path]:
    """A PR head prepared by the runner: its bundle in a folder store, its head pointing at it."""
    root, base, head = _repo(tmp_path)
    store = FolderStore(tmp_path / 'store', 'r')
    monkeypatch.setattr(fb, 'store_for', lambda *_a, **_k: store)
    monkeypatch.setattr(fb, 'resolve', lambda entry, dest, **_k: store.get(Ref.of(entry), dest))
    pull = PullRequest(7, 't', 'open', 'the body', 'u', 'a', 'pr/x', 'main', head_sha=head)
    forge = FakeForge(pull, git_out(root, 'diff', '--full-index', base, head))
    said = fb.prepare(root, forge, 7)  # type: ignore[arg-type]
    assert said.startswith(f'#7 {head[:12]}: bundle sha256:')
    return forge, root


def _judged(forge: FakeForge, out: str) -> tuple[list[str], list[tuple[str, ...]]]:
    seen: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], _where: Path) -> str:
        seen.append(tuple(argv))
        return out

    return fb.judge_pending(forge, runtimes=_RUNTIMES, run=run), seen  # type: ignore[arg-type]


def test_prepare_points_the_head_at_its_stored_bundle(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    (status,) = forge.statuses[forge.pull.head_sha]
    assert (status['context'], status['state']) == (fb.BUNDLE_CONTEXT, 'success')
    assert status['description'].startswith('sha256:')
    assert fb.ref_of_pointer(status['target_url']).backend == 'folder'


def test_the_judge_approves_a_clean_head_once(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    said, seen = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (review,) = forge.reviews
    assert (review['event'], review['commit_id']) == ('APPROVED', forge.pull.head_sha)
    (argv,) = seen
    assert argv[:4] == ('py', '-m', 'ai_lab.review', '--bundle')
    assert '--pr-body' in argv
    tree = Path(argv[4])
    assert not tree.exists()  # the plain files lived only for the one command
    assert _judged(forge, _findings(None)) == ([], [])  # idempotent per head: nothing judged again


def test_a_blocking_finding_requests_changes(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    _judged(forge, _findings('HIGH'))
    (review,) = forge.reviews
    assert review['event'] == 'REQUEST_CHANGES'
    assert 'F-0123456789ab' in review['body']


def test_a_bundle_the_forge_diff_disowns_is_refused_as_request_changes(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    forge.diff = forge.diff.replace('kept.py', 'other.py')
    said, seen = _judged(forge, _findings(None))
    assert seen == []  # the reviewer never read an unverified byte
    (review,) = forge.reviews
    assert review['event'] == 'REQUEST_CHANGES'
    assert 'refused' in review['body']
    assert said == [f'#7 {forge.pull.head_sha[:12]}: REQUEST_CHANGES']


def test_a_failing_command_posts_nothing_and_is_retried(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    said, _ = _judged(forge, 'not json')
    assert forge.reviews == []
    assert 'retried' in said[0]


def test_a_serve_repo_is_never_judged(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    forge.manifest = _JUDGE_TOML.replace('where = "judge"', 'where = "serve"')
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.reviews) == ([], [])
    assert 'reviews no PR' in said[0]


def test_a_judge_repo_is_never_served(tmp_path: Path) -> None:
    review = Review(where=JUDGE, judge_login='review-bot')
    assert review_tick(tmp_path, object(), review, base='main', host='h') == ()  # type: ignore[arg-type]


def test_the_declaration_names_one_mode_and_a_bundle_command_that_reads_the_bundle() -> None:
    assert review_from(_JUDGED, 'x').where == JUDGE
    with pytest.raises(ValueError, match='judge_login'):
        review_from('[tool.dev_lab.review]\nwhere = "judge"\n', 'x')
    with pytest.raises(ValueError, match='where'):
        review_from('[tool.dev_lab.review]\nwhere = "both"\n', 'x')
    with pytest.raises(ValueError, match='bundle'):
        review_from('[tool.dev_lab.review]\nbundle = ["reviewer"]\n', 'x')
    with pytest.raises(ValueError, match='redeclares'):
        review_from(f'[tool.dev_lab.review]\nbundle = {json.dumps(list(FAMILY_BUNDLE))}\n', 'x')
    argv = command_for(Review(), 'a..b', _RUNTIMES, bundle=True)
    assert argv[:5] == ['py', '-m', 'ai_lab.review', '--bundle', '{bundle}']


def test_a_pointer_round_trips_and_anything_else_is_refused() -> None:
    ref = Ref('folder', 'r/2026/11/03/x.tar.gz', 10, 'ab' * 32)
    assert fb.ref_of_pointer(fb.pointer(ref)) == ref
    for bad in ('https://x/y', 'artefact:?backend=folder'):
        with pytest.raises(BundleRefused, match='Ref'):
            fb.ref_of_pointer(bad)


def _repost(forge: FakeForge, login: str) -> None:
    """*login* re-posts the head's pointer as its own: the newest review/bundle status, a forged one."""
    (honest,) = forge.statuses[forge.pull.head_sha]
    forge.poster = login
    forge.call(
        'POST',
        f'{forge.repo}/statuses/{forge.pull.head_sha}',
        {k: honest[k] for k in ('context', 'state', 'description', 'target_url')}
        | {'target_url': 'artefact:?backend=folder&ref=forged&bytes=1&sha256=' + '0' * 64},
    )


def test_a_pointer_only_another_login_posted_is_ignored(prepared: tuple[FakeForge, Path]) -> None:
    """PLANTED CONTROL: the same head pointed at by the CI (null creator) is approved above."""
    forge, _ = prepared
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': 'mallory'}
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.reviews) == ([], [], [])


def test_a_forged_newer_pointer_neither_griefs_nor_shadows_the_ci_one(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    _repost(forge, 'mallory')
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_a_declared_preparer_s_pointer_is_read(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': 'prep-bot'}
    forge.manifest = _JUDGE_TOML + 'preparers = ["prep-bot"]\n'
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_a_host_that_is_not_the_declared_judge_judges_nothing(prepared: tuple[FakeForge, Path]) -> None:
    forge, _ = prepared
    forge.login = 'someone-else'
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.reviews) == ([], [])
    assert 'judge_login' in said[0]
