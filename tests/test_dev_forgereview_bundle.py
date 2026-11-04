"""The bundle review: the runner prepares and points, the judge verifies, reviews and posts a PR review once per head.

The judge trusts nothing the producer wrote that it can read or derive from the forge (D3). PLANTED CONTROLS: the
honest prepared head is APPROVED, and against it a tampered forge diff, another merge base, a Ref not bound to the
head, a corrupt archive and a binary code file are each REQUEST_CHANGES; a pointer from a login or a run that is not
the base's prepare run is ignored; a failure to read posts nothing and never stops the next PR; a blocking finding is
REQUEST_CHANGES; a head already judged is not judged again; a ``serve`` repo is never judged and a ``judge`` repo is
never served; a reviewer that did not run posts nothing.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import git_out, run_git

from dev_lab.dev import forgereview_bundle as fb
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev._forgebackends import GITEA
from dev_lab.dev.artefacts import FolderStore, Ref, pack, run_id
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_declared import FAMILY_BUNDLE, JUDGE, Review, command_for, review_from
from dev_lab.dev.reviewbundle import BundleRefused

_JUDGED = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "review-bot"\n'
_JUDGE_TOML = '[tool.dev_lab.integrator]\nintegration = "main"\n' + _JUDGED
_RUNTIMES = {'ai_lab': {'python': 'py'}}
_RUN = 'https://forge.example.org/o/r/actions/runs/1'
_POISONED = 'b' * 40


def _findings(severity: str | None, *, statuses: tuple[str, ...] = ('ok',)) -> str:
    rows = [
        {'name': f'r{at}', 'provider': 'anthropic', 'status': status, 'dropped_findings': 0}
        for at, status in enumerate(statuses)
    ]
    found = (
        []
        if severity is None
        else [{
            'id': 'F-0123456789ab', 'severity': severity, 'security': False, 'rule': 'R', 'file': 'kept.py',
            'anchor': 'x', 'summary': 's', 'category': 'Bug', 'status': 'OPEN', 'suggestion': '', 'detail': '',
            'confidence': 'single', 'reviewers': [{'name': 'r0', 'provider': 'anthropic'}],
        }]
    )  # fmt: skip
    return json.dumps({'schema_version': 3, 'range': 'a..b', 'profiles': ['r'], 'reviewers': rows, 'findings': found})


def _prepare_run(head: str, *, number: int = 7, event: str = 'pull_request_target') -> dict[str, Any]:
    path = f'{fb.PREPARE_WORKFLOW}@refs/pull/{number}/head'
    return {'id': number, 'head_sha': head, 'event': event, 'path': path, 'html_url': _RUN, 'conclusion': ''}


@dataclass
class FakeForge:
    """One Gitea repository as the two sides see it: statuses, reviews, runs, files by ref, the PRs and diffs."""

    pull: PullRequest
    diffs: dict[int, str]
    merge_base: str
    manifest: str = _JUDGE_TOML
    login: str = 'review-bot'
    poster: str | None = None  # who the runner's status is recorded as: None is Gitea's Actions (null creator)
    others: list[PullRequest] = field(default_factory=list)  # listed BEFORE pull
    statuses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reviews: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    runs: list[dict[str, Any]] = field(default_factory=list)
    forge: Forge = field(default_factory=lambda: Forge('forge.example.org', 'o', 'r'))
    backend: Any = GITEA
    repo: str = '/api/v1/repos/o/r'

    @property
    def diff(self) -> str:
        return self.diffs[self.pull.number]

    def _pulls(self) -> dict[int, PullRequest]:
        return {one.number: one for one in [*self.others, self.pull]}

    def pr_view(self, number: int) -> PullRequest:
        return self._pulls()[number]

    def whoami(self) -> str:
        return self.login

    def pull_diff(self, number: int) -> str:
        if number not in self.diffs:
            msg = f'the forge serves no diff of #{number}'
            raise OSError(msg)
        return self.diffs[number]

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, durable: object = None) -> Any:  # noqa: ANN401
        del durable
        path = path.partition('?')[0]
        return self._post(path, body or {}) if method == 'POST' else self._get(path)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path.endswith('/reviews'):
            number = int(path.split('/')[-2])
            rows = self.reviews.setdefault(number, [])
            rows.append({'id': len(rows) + 1, 'user': {'login': self.login}, 'state': body['event'], **body})
            return rows[-1]
        rows = self.statuses.setdefault(path.rsplit('/', 1)[1], [])
        creator = None if self.poster is None else {'login': self.poster}
        rows.append({'id': len(rows) + 1, 'creator': creator, **body})
        return rows[-1]

    def _get(self, path: str) -> Any:  # noqa: ANN401
        manifest = {'content': base64.b64encode(self.manifest.encode()).decode()}
        answers: dict[str, Any] = {
            self.repo: {'default_branch': 'main'},
            f'{self.repo}/contents/pyproject.toml': manifest,
            f'{self.repo}/pulls': [_raw(one) for one in self._pulls().values()],
            f'{self.repo}/actions/runs': {'workflow_runs': list(self.runs)},
        }
        for number, one in self._pulls().items():
            answers[f'{self.repo}/pulls/{number}'] = {'merge_base': self.merge_base}
            answers[f'{self.repo}/pulls/{number}/reviews'] = list(self.reviews.get(number, []))
            answers[f'{self.repo}/issues/{number}/comments'] = []
            answers[f'{self.repo}/statuses/{one.head_sha}'] = list(self.statuses.get(one.head_sha, []))
        return answers[path]

    def verdicts(self, number: int = 7) -> list[dict[str, Any]]:
        return self.reviews.get(number, [])


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
    (root / 'logo.png').write_bytes(b'\x89PNG\x00\x01')  # binary, and no code: listed, approved
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'head')
    return root, base, git_out(root, 'rev-parse', 'HEAD')


@dataclass
class Prepared:
    forge: FakeForge
    root: Path
    store: FolderStore
    fetched: list[str]


def _prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root: Path, base: str, head: str) -> Prepared:
    store = FolderStore(tmp_path / 'store', 'r')
    fetched: list[str] = []

    def resolve(entry: dict[str, Any], dest: Path, **_k: object) -> Path:
        fetched.append(entry['ref'])
        return store.get(Ref.of(entry), dest)

    monkeypatch.setattr(fb, 'store_for', lambda *_a, **_k: store)
    monkeypatch.setattr(fb, 'resolve', resolve)
    monkeypatch.setattr(fb, 'job_run_url', lambda _client: _RUN)
    pull = PullRequest(7, 't', 'open', 'the body', 'u', 'a', 'pr/x', 'main', head_sha=head)
    diffs = {7: git_out(root, 'diff', '--full-index', base, head)}
    forge = FakeForge(pull, diffs, base, runs=[_prepare_run(head)])
    said = fb.prepare(root, forge, 7)  # type: ignore[arg-type]
    assert said.startswith(f'#7 {head[:12]}: bundle sha256:')
    return Prepared(forge, root, store, fetched)


@pytest.fixture
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Prepared:
    """A PR head prepared by the base's prepare run: its bundle in a folder store, its head pointing at it."""
    return _prepared(tmp_path, monkeypatch, *_repo(tmp_path))


def _judged(
    forge: FakeForge, out: str, *, read: list[dict[str, str]] | None = None
) -> tuple[list[str], list[tuple[str, ...]]]:
    seen: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], _where: Path, env: dict[str, str]) -> str:
        seen.append(tuple(argv))
        tree = Path(argv[argv.index('--bundle') + 1])
        disposed = Path(argv[argv.index('--disposed') + 1]).read_text(encoding='utf-8')
        if read is not None:
            read.append({'diff': (tree / 'diff.patch').read_text(encoding='utf-8'), 'disposed': disposed, **env})
        return out

    return fb.judge_pending(forge, runtimes=_RUNTIMES, run=run), seen  # type: ignore[arg-type]


def test_prepare_points_the_head_at_its_stored_bundle_and_its_run(prepared: Prepared) -> None:
    (status,) = prepared.forge.statuses[prepared.forge.pull.head_sha]
    assert (status['context'], status['state']) == (fb.BUNDLE_CONTEXT, 'success')
    assert status['description'].startswith('sha256:')
    assert fb.ref_of_pointer(status['target_url']).backend == 'folder'
    assert 'run=' in status['target_url']


def test_the_judge_approves_a_clean_head_once_reading_the_forges_diff(prepared: Prepared) -> None:
    forge, read = prepared.forge, []
    said, seen = _judged(forge, _findings(None), read=read)
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (review,) = forge.verdicts()
    assert (review['event'], review['commit_id']) == ('APPROVED', forge.pull.head_sha)
    (argv,) = seen
    assert argv[:4] == ('py', '-m', 'ai_lab.review', '--bundle')
    assert '--pr-body' in argv
    assert not Path(argv[4]).exists()  # the plain files lived only for the one command
    assert read[0]['diff'] == forge.diff  # the FORGE's diff, never the producer's
    assert 'GIT_DIR' in read[0]  # no repository reachable through git's discovery
    assert _judged(forge, _findings(None)) == ([], [])  # idempotent per head: nothing judged again


def test_a_dismissed_verdict_is_judged_again(prepared: Prepared) -> None:
    forge = prepared.forge
    _judged(forge, _findings(None))
    forge.verdicts()[0]['dismissed'] = True
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_the_forges_disposals_reach_the_reviewer(prepared: Prepared, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fb, 'upheld', lambda _bodies: {'F-0123456789ab': 'adjudicated false positive'})
    read: list[dict[str, str]] = []
    _judged(prepared.forge, _findings(None), read=read)
    assert 'F-0123456789ab' in read[0]['disposed']


def test_a_blocking_finding_requests_changes(prepared: Prepared) -> None:
    _judged(prepared.forge, _findings('HIGH'))
    (review,) = prepared.forge.verdicts()
    assert review['event'] == 'REQUEST_CHANGES'
    assert 'F-0123456789ab' in review['body']


@pytest.mark.parametrize('statuses', [('ok', 'timeout'), ('skipped',), ('exhausted',)])
def test_a_reviewer_that_did_not_run_posts_nothing(prepared: Prepared, statuses: tuple[str, ...]) -> None:
    said, _ = _judged(prepared.forge, _findings(None, statuses=statuses))
    assert prepared.forge.verdicts() == []
    assert 'nothing posted' in said[0]


def test_a_bundle_the_forge_diff_disowns_is_refused_as_request_changes(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.diffs[7] = forge.diff.replace('kept.py', 'other.py')
    said, seen = _judged(forge, _findings(None))
    assert seen == []  # the reviewer never read an unverified byte
    (review,) = forge.verdicts()
    assert review['event'] == 'REQUEST_CHANGES'
    assert 'refused' in review['body']
    assert said == [f'#7 {forge.pull.head_sha[:12]}: REQUEST_CHANGES']


def test_a_bundle_of_another_merge_base_is_refused(prepared: Prepared) -> None:
    prepared.forge.merge_base = 'e' * 40
    _judged(prepared.forge, _findings(None))
    (review,) = prepared.forge.verdicts()
    assert (review['event'], 'merge base' in review['body']) == ('REQUEST_CHANGES', True)


@pytest.mark.parametrize(
    'key', ['../../../etc/forge-bot/gitea-token', 'r/2026/11/03/{other}-review-{digest}-20261103T000000Z.tar.gz']
)
def test_a_ref_not_bound_to_the_head_and_digest_is_never_fetched(prepared: Prepared, key: str) -> None:
    forge = prepared.forge
    (status,) = forge.statuses[forge.pull.head_sha]
    ref = fb.ref_of_pointer(status['target_url'])
    digest = status['description'].removeprefix('sha256:')[:16]
    forged = Ref(ref.backend, key.format(other='c' * 12, digest=digest), ref.bytes, ref.sha256)
    status['target_url'] = fb.pointer(forged, run=_RUN)
    _judged(forge, _findings(None))
    assert prepared.fetched == []
    (review,) = forge.verdicts()
    assert review['event'] == 'REQUEST_CHANGES'


def test_a_binary_change_to_code_is_never_approved_unread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, base, _ = _repo(tmp_path)
    (root / 'tool.py').write_bytes(b'import os\x00\nos.system("x")\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'hide')
    prepared = _prepared(tmp_path, monkeypatch, root, base, git_out(root, 'rev-parse', 'HEAD'))
    said, seen = _judged(prepared.forge, _findings(None))
    assert seen == []
    (review,) = prepared.forge.verdicts()
    assert (review['event'], 'tool.py' in review['body']) == ('REQUEST_CHANGES', True)
    assert 'logo.png' not in review['body']  # a binary that is not code is no finding
    assert said[0].endswith('REQUEST_CHANGES')


def test_a_failing_command_posts_nothing_and_is_retried(prepared: Prepared) -> None:
    said, _ = _judged(prepared.forge, 'not json')
    assert prepared.forge.verdicts() == []
    assert 'retried' in said[0]


def _poison(prepared: Prepared, *, diff: str | None) -> None:
    """PR #6 (listed first) points, from a trusted run, at an archive with no bundle.json; *diff* its forge diff."""
    forge, store = prepared.forge, prepared.store
    tree = prepared.root.parent / 'poison'
    tree.mkdir()
    (tree / 'other.txt').write_text('{}', encoding='utf-8')
    archive = pack(tree, [tree / 'other.txt'], prepared.root.parent / 'poison.tar.gz')
    ref = store.put(run_id(_POISONED, 'review', '1' * 16, datetime(2026, 11, 3, tzinfo=UTC)), archive)
    forge.others.append(PullRequest(6, 'p', 'open', '', 'u', 'a', 'pr/p', 'main', head_sha=_POISONED))
    forge.runs.append(_prepare_run(_POISONED, number=6))
    forge.statuses[_POISONED] = [{
        'id': 1, 'creator': None, 'context': fb.BUNDLE_CONTEXT, 'state': 'success',
        'description': 'sha256:' + '1' * 64, 'target_url': fb.pointer(ref, run=_RUN),
    }]  # fmt: skip
    if diff is not None:
        forge.diffs[6] = diff


def test_a_corrupt_archive_is_request_changes_and_the_next_pr_is_still_judged(prepared: Prepared) -> None:
    _poison(prepared, diff='')
    said, _ = _judged(prepared.forge, _findings(None))
    assert said == [f'#6 {_POISONED[:12]}: REQUEST_CHANGES', f'#7 {prepared.forge.pull.head_sha[:12]}: APPROVED']
    (review,) = prepared.forge.verdicts(6)
    assert 'bundle.json' in review['body'] or 'archive' in review['body']


def test_a_read_failure_posts_nothing_and_the_next_pr_is_still_judged(prepared: Prepared) -> None:
    _poison(prepared, diff=None)  # the forge serves no diff of #6: a read failure
    said, _ = _judged(prepared.forge, _findings(None))
    assert said[0].startswith(f'#6 {_POISONED[:12]}')
    assert 'retried' in said[0]
    assert said[-1] == f'#7 {prepared.forge.pull.head_sha[:12]}: APPROVED'
    assert prepared.forge.verdicts(6) == []


def test_a_null_creator_pointer_not_from_the_bases_prepare_run_is_ignored(prepared: Prepared) -> None:
    """A PR-head workflow (``pull_request``) posts with a null creator too; only the base's run is trusted."""
    forge = prepared.forge
    forge.runs[0]['event'] = 'pull_request'
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts()) == ([], [], [])


def test_a_serve_repo_is_never_judged(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.manifest = _JUDGE_TOML.replace('where = "judge"', 'where = "serve"')
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.verdicts()) == ([], [])
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
    assert fb.ref_of_pointer(fb.pointer(ref, run=_RUN)) == ref
    for bad in ('https://x/y', 'artefact:?backend=folder'):
        with pytest.raises(BundleRefused, match='Ref'):
            fb.ref_of_pointer(bad)


def test_a_pointer_only_another_login_posted_is_ignored(prepared: Prepared) -> None:
    """PLANTED CONTROL: the same head pointed at by the base's prepare run is approved above."""
    forge = prepared.forge
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': 'mallory'}
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts()) == ([], [], [])


def test_a_forged_newer_pointer_neither_griefs_nor_shadows_the_ci_one(prepared: Prepared) -> None:
    forge = prepared.forge
    (honest,) = forge.statuses[forge.pull.head_sha]
    forge.poster = 'mallory'
    forge.call('POST', f'{forge.repo}/statuses/{forge.pull.head_sha}', {
        **{k: honest[k] for k in ('context', 'state', 'description')},
        'target_url': 'artefact:?backend=folder&ref=forged&bytes=1&sha256=' + '0' * 64,
    })  # fmt: skip
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_a_declared_preparer_s_pointer_is_read(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': 'prep-bot'}
    forge.runs.clear()
    forge.manifest = _JUDGE_TOML + 'preparers = ["prep-bot"]\n'
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_a_host_that_is_not_the_declared_judge_judges_nothing(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.login = 'someone-else'
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.verdicts()) == ([], [])
    assert 'judge_login' in said[0]
