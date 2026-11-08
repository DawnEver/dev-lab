"""The bundle review: the runner prepares, the judge finds the bundle itself, verifies, reviews and posts once per head.

The judge trusts nothing the producer wrote that it can read or derive from the forge (D3), and takes WHICH bundle
to read from nothing a PR-head job can write (F-680a6bd606f0). PLANTED CONTROLS: the honest prepared head -- its
bundle the base's successful prepare run's own artifact -- is APPROVED, and against it a newer null-creator pointer
naming that very run, a run of another workflow, event or pull request (on GitHub also a fork's run, which names no
pull request, and a run naming two), a prepare run that failed or was cancelled, and a GitHub bot pointer are each
never read -- the run's artifact on BOTH forges, each through its own fake; a tampered forge diff,
another merge base, a Ref not bound to the head, a corrupt artifact and a binary code file are each REQUEST_CHANGES;
a failure to read posts nothing and never stops the next PR; a security finding is REQUEST_CHANGES; a head
already judged is not judged again; a ``serve`` repo is never judged and a ``judge`` repo is never served; a reviewer
that did not run posts nothing.
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
from dev_lab.dev import forgereview_pointer as fp
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev._forgebackends import ACTIONS_BOT, GITEA, GITHUB, Backend
from dev_lab.dev.actionsartifact import zipped
from dev_lab.dev.artefactfolder import FolderStore
from dev_lab.dev.artefactpack import pack
from dev_lab.dev.artefacts import Config, Ref
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeapp import App
from dev_lab.dev.forgecontexts import JUDGE_CHECK
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_claim import DUE
from dev_lab.dev.forgereview_declared import FAMILY_BUNDLE, JUDGE, Review, command_for, review_from
from dev_lab.dev.platformparts import REVIEW_CONTEXT
from dev_lab.dev.reviewbundle import BundleRefused
from dev_lab.dev.reviewgate import PREPARE_WORKFLOW

_JUDGED = '[tool.dev_lab.review]\nwhere = "judge"\njudge_login = "review-bot"\n'
_JUDGE_TOML = '[tool.dev_lab.integrator]\nintegration = "main"\n' + _JUDGED
_PREPARER = _JUDGE_TOML + 'preparers = ["prep-bot"]\n'
_RUNTIMES = {'ai_lab': {'python': 'py'}}
_POISONED = 'b' * 40
_ACTIONS = {'GITEA_ACTIONS': 'true', 'GITHUB_ACTIONS': 'true'}  # prepare inside a Gitea Actions job
#: Each forge as the judge's client reaches it: its host, and its repository's API collection.
_FORGES = {
    GITEA: (Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r'),
    GITHUB: (Forge('github.com', 'o', 'r'), '/repos/o/r'),
}
#: The key each forge stamps a run's CREATION under.
_CREATED = {GITEA: 'created', GITHUB: 'created_at'}


def _findings(severity: str | None, *, statuses: tuple[str, ...] = ('ok',), security: bool = False) -> str:
    rows = [
        {'name': f'r{at}', 'provider': 'anthropic', 'status': status, 'dropped_findings': 0}
        for at, status in enumerate(statuses)
    ]
    found = (
        []
        if severity is None
        else [{
            'id': 'F-0123456789ab', 'severity': severity, 'security': security, 'rule': 'R', 'file': 'kept.py',
            'anchor': 'x', 'summary': 's', 'category': 'Bug', 'status': 'OPEN', 'suggestion': '', 'detail': '',
            'confidence': 'single', 'reviewers': [{'name': 'r0', 'provider': 'anthropic'}],
        }]
    )  # fmt: skip
    return json.dumps({'schema_version': 3, 'range': 'a..b', 'profiles': ['r'], 'reviewers': rows, 'findings': found})


def _url(run: int) -> str:
    return f'https://forge.example.org/o/r/actions/runs/{run}'


def _prepare_run(
    head: str, *, number: int = 7, run: int = 0, event: str = 'pull_request_target', conclusion: str = '',
    workflow: str = PREPARE_WORKFLOW, backend: Backend = GITEA, pulls: list[int] | None = None,
) -> dict[str, Any]:  # fmt: skip
    """A run at *head* as *backend* lists it; by default the base's prepare run of PR *number*, still going.

    Gitea names the pull request in the run's ``path`` and stamps ``created``; GitHub lists the workflow file alone,
    the pull requests (*pulls*, default ``[number]``) in ``pull_requests``, and stamps ``created_at``.
    """
    run = run or number
    shared = {'id': run, 'head_sha': head, 'event': event, 'html_url': _url(run), 'conclusion': conclusion}
    if backend is GITHUB:
        listed = [{'number': one, 'head': {'sha': head}} for one in ([number] if pulls is None else pulls)]
        path = f'.github/workflows/{workflow}'
        return {**shared, 'path': path, 'pull_requests': listed, _CREATED[GITHUB]: '2026-11-04T10:00:00Z'}
    path = f'{workflow}@refs/pull/{number}/head'
    return {**shared, 'path': path, _CREATED[GITEA]: '2026-11-04T10:00:00Z', 'started_at': '2026-11-04T10:00:00Z'}


@dataclass
class FakeForge:
    """One Gitea repository as the two sides see it: statuses, reviews, runs and their artifacts, files, PRs, diffs."""

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
    #: Every Actions artifact by id: the run it is attached to, its name, its zip.
    artifacts: dict[int, tuple[int, str, bytes]] = field(default_factory=dict)
    downloaded: list[int] = field(default_factory=list)
    #: Each pull's issue timeline as the forge lists it; ``None`` is a timeline the forge will not serve.
    timelines: dict[int, list[dict[str, Any]] | None] = field(default_factory=dict)
    #: Every GET path the judge asked, query included.
    asked: list[str] = field(default_factory=list)
    forge: Forge = field(default_factory=lambda: Forge('forge.example.org', 'o', 'r'))
    backend: Any = GITEA
    repo: str = '/api/v1/repos/o/r'
    #: The GitHub App this judge authenticates as (:mod:`dev_lab.dev.forgeapp`), else ``None``: a login.
    app: App | None = None
    #: Every check run at each head, whoever posted it.
    checks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

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

    def attach(self, run: int, name: str, members: dict[str, bytes]) -> str:
        """What only run *run*'s own job can do: attach an artifact to that run."""
        ident = 900 + len(self.artifacts)
        self.artifacts[ident] = (run, name, zipped(members))
        return str(ident)

    def download(self, url: str) -> bytes:
        ident = int(url.split('/actions/artifacts/')[1].split('/', maxsplit=1)[0])
        self.downloaded.append(ident)
        return self.artifacts[ident][2]

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, durable: object = None) -> Any:  # noqa: ANN401
        del durable
        if method == 'GET':
            self.asked.append(path)
        path = path.partition('?')[0]
        return self._post(path, body or {}) if method == 'POST' else self._get(path)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path.endswith('/check-runs'):
            assert self.app is not None
            runs = self.checks.setdefault(body['head_sha'], [])
            runs.append({'id': len(runs) + 1, 'app': {'id': self.app.app_id, 'slug': self.app.slug}, **body})
            return runs[-1]
        if path.endswith('/reviews'):
            number = int(path.split('/')[-2])
            rows = self.reviews.setdefault(number, [])
            state = {'APPROVE': 'APPROVED'}.get(body['event'], body['event'])  # GitHub's event names its verb
            rows.append({'id': len(rows) + 1, 'user': {'login': self.login}, 'state': state, **body})
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
        for run in self.runs:
            rows = [
                {'id': ident, 'name': name, 'size_in_bytes': len(data), 'expired': False}
                for ident, (owner, name, data) in self.artifacts.items() if owner == run['id']
            ]  # fmt: skip
            answers[f'{self.repo}/actions/runs/{run["id"]}/artifacts'] = {'artifacts': rows, 'total_count': len(rows)}
        for number, one in self._pulls().items():
            answers[f'{self.repo}/pulls/{number}'] = {'merge_base': self.merge_base}
            compare = f'{self.repo}/compare/{one.base}...{one.head_sha}'
            answers[compare] = {'merge_base_commit': {'sha': self.merge_base}}
            answers[f'{self.repo}/pulls/{number}/reviews'] = list(self.reviews.get(number, []))
            answers[f'{self.repo}/issues/{number}/comments'] = []
            answers[f'{self.repo}/issues/{number}/timeline'] = self.timelines.get(number, [])
            answers[f'{self.repo}/statuses/{one.head_sha}'] = list(self.statuses.get(one.head_sha, []))
            answers[f'{self.repo}/commits/{one.head_sha}/statuses'] = list(self.statuses.get(one.head_sha, []))
            answers[f'{self.repo}/commits/{one.head_sha}/check-runs'] = {
                'check_runs': self.checks.get(one.head_sha, [])
            }
        if answers[path] is None:
            msg = f'the forge serves nothing at {path}'
            raise OSError(msg)
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


def _prepared(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    base: str,
    head: str,
    *,
    configs: list[Config] | None = None,
    hosted: bool = False,
    backend: Backend = GITEA,
) -> Prepared:
    """PR #7 prepared by the base's prepare run (its own artifact) on *backend* -- or, *hosted*, by the preparer.

    On Gitea the run's job uploads the artifact itself; on GitHub ``prepare`` writes the bundle where the
    workflow's upload step takes it from, and that step attaches it to the run.
    """
    store = FolderStore(tmp_path / 'store', 'r')
    fetched: list[str] = []

    def resolve(entry: dict[str, Any], dest: Path, **_k: object) -> Path:
        fetched.append(entry['ref'])
        return store.get(Ref.of(entry), dest)

    def store_for(config: Config, *_a: object, **_k: object) -> FolderStore:
        if configs is not None:
            configs.append(config)
        return store

    monkeypatch.setattr(fp, 'store_for', store_for)
    monkeypatch.setattr(fp, 'resolve', resolve)
    pull = PullRequest(7, 't', 'open', 'the body', 'u', 'a', 'pr/x', 'main', head_sha=head)
    diffs = {7: git_out(root, 'diff', '--full-index', base, head)}
    if hosted:
        forge = FakeForge(pull, diffs, base, manifest=_PREPARER, poster='prep-bot')
        said = fp.prepare(root, forge, 7, env={})  # type: ignore[arg-type]
    else:
        run = _prepare_run(head, backend=backend)
        where, repo = _FORGES[backend]
        forge = FakeForge(pull, diffs, base, runs=[run], forge=where, backend=backend, repo=repo)
        monkeypatch.setattr(fp, 'upload', lambda name, members, **_env: forge.attach(run['id'], name, dict(members)))
        temp = tmp_path / 'runner-temp'
        env = {'GITHUB_ACTIONS': 'true', 'RUNNER_TEMP': str(temp)} if backend is GITHUB else _ACTIONS
        said = fp.prepare(root, forge, 7, env=env)  # type: ignore[arg-type]
        if backend is GITHUB:  # the workflow's actions/upload-artifact step attaches what prepare left
            forge.attach(run['id'], fp.ARTIFACT, {fp.BUNDLE_FILE: (temp / fp.ARTIFACT / fp.BUNDLE_FILE).read_bytes()})
        run['conclusion'] = 'success'
    assert said.startswith(f'#7 {head[:12]}: bundle sha256:')
    return Prepared(forge, root, store, fetched)


@pytest.fixture(params=[GITEA, GITHUB], ids=['gitea', 'github'])
def prepared(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> Prepared:
    """A PR head prepared by the base's prepare run on each forge: its bundle that run's artifact, nothing posted."""
    return _prepared(tmp_path, monkeypatch, *_repo(tmp_path), backend=request.param)


@pytest.fixture
def on_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Prepared:
    """A PR head prepared by the base's prepare run on GitHub."""
    return _prepared(tmp_path, monkeypatch, *_repo(tmp_path), backend=GITHUB)


@pytest.fixture
def hosted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Prepared:
    """A PR head prepared on the declared preparer's host: its bundle in a folder store, its head pointing at it."""
    return _prepared(tmp_path, monkeypatch, *_repo(tmp_path), hosted=True)


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

    for one in forge._pulls().values():  # the merge decision called each head due: the review is the last gate
        rows = forge.statuses.setdefault(one.head_sha, [])
        if not any(row['context'] == REVIEW_CONTEXT for row in rows):
            rows.append({'id': len(rows) + 1, 'creator': None, 'context': REVIEW_CONTEXT, 'state': 'pending',
                         'description': DUE, 'target_url': ''})  # fmt: skip
    return fb.judge_pending(forge, runtimes=_RUNTIMES, run=run), seen  # type: ignore[arg-type]


def _forge_a_bundle(prepared: Prepared, tmp_path: Path) -> tuple[Ref, str]:
    """What a PR-head job can write: a bundle of its own making, in the store its job token reaches."""
    tree = tmp_path / 'forged'
    tree.mkdir()
    (tree / fp.BUNDLE_FILE).write_text('{"version": 1}', encoding='utf-8')
    archive = pack(tree, [tree / fp.BUNDLE_FILE], tmp_path / 'forged.tar.gz').path
    head = prepared.forge.pull.head_sha
    ident = f'{head[:12]}-review-{"f" * 16}-20261104T000000Z'
    return prepared.store.put(ident, archive), 'sha256:' + 'f' * 64


def test_prepare_in_actions_attaches_the_bundle_to_its_own_run_and_posts_nothing(prepared: Prepared) -> None:
    forge = prepared.forge
    ((run, name, _),) = forge.artifacts.values()
    assert (run, name) == (forge.runs[0]['id'], fp.ARTIFACT)
    assert forge.statuses == {}
    assert prepared.store.list(None) == ()


def test_prepare_in_a_github_job_with_nowhere_to_leave_the_bundle_is_refused(on_github: Prepared) -> None:
    """PLANTED CONTROL: the same job with RUNNER_TEMP set prepared the fixture's bundle."""
    with pytest.raises(BundleRefused, match='RUNNER_TEMP'):
        fp.prepare(on_github.root, on_github.forge, 7, env={'GITHUB_ACTIONS': 'true'})  # type: ignore[arg-type]


def test_a_preparer_s_host_points_the_head_at_its_stored_bundle(hosted: Prepared) -> None:
    (status,) = hosted.forge.statuses[hosted.forge.pull.head_sha]
    assert (status['context'], status['state']) == (fp.BUNDLE_CONTEXT, 'success')
    assert status['description'].startswith('sha256:')
    assert fp.ref_of_pointer(status['target_url']).backend == 'folder'


def test_the_judge_approves_a_clean_head_once_reading_the_forges_diff(prepared: Prepared) -> None:
    forge, read = prepared.forge, []
    said, seen = _judged(forge, _findings(None), read=read)
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (review,) = forge.verdicts()
    assert (review['state'], review['commit_id']) == ('APPROVED', forge.pull.head_sha)
    (argv,) = seen
    assert argv[:4] == ('py', '-m', 'ai_lab.review', '--bundle')
    assert '--pr-body' in argv
    assert not Path(argv[4]).exists()  # the plain files lived only for the one command
    assert read[0]['diff'] == forge.diff  # the FORGE's diff, never the producer's
    assert 'GIT_DIR' in read[0]  # no repository reachable through git's discovery
    assert _judged(forge, _findings(None)) == ([], [])  # idempotent per head: nothing judged again


def test_a_forged_newer_pointer_naming_the_honest_run_is_never_what_the_judge_reads(
    prepared: Prepared, tmp_path: Path
) -> None:
    """F-680a6bd606f0: a PR-head job posts a newer null-creator pointer naming the honest run's public URL.

    PLANTED CONTROL: the honest run's own artifact is what is judged -- APPROVED, read from that artifact -- and the
    forged Ref, which a judge trusting the pointer would fetch and refuse, is never fetched.
    """
    forge = prepared.forge
    ref, digest = _forge_a_bundle(prepared, tmp_path)
    honest_run = forge.runs[0]
    forge.call('POST', f'{forge.repo}/statuses/{forge.pull.head_sha}', {
        'context': fp.BUNDLE_CONTEXT, 'state': 'success', 'description': digest,
        'target_url': fp.pointer(ref) + '&run=' + honest_run['html_url'],
    })  # fmt: skip
    said, seen = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    assert len(seen) == 1
    assert prepared.fetched == []
    ((ident, (run, _, _)),) = forge.artifacts.items()
    assert (forge.downloaded, run) == ([ident], honest_run['id'])


@pytest.mark.parametrize('conclusion', ['failure', 'cancelled'])
def test_a_prepare_run_that_did_not_succeed_is_no_source(prepared: Prepared, conclusion: str) -> None:
    """Its artifact exists, and an OLDER run succeeded: the newest concluded run decides, and it did not succeed."""
    forge = prepared.forge
    newer = _prepare_run(forge.pull.head_sha, run=8, conclusion=conclusion, backend=forge.backend)
    forge.runs.append(newer)
    forge.attach(8, fp.ARTIFACT, {fp.BUNDLE_FILE: b'{}'})
    forge.runs.sort(key=lambda run: -run['id'])
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts(), forge.downloaded) == ([], [], [], [])


def _retarget(forge: FakeForge, at: str, *, key: str = 'type', kind: str = 'change_target_branch') -> None:
    """The PR's base was changed at *at* (Gitea's ``change_target_branch``; GitHub's ``base_ref_changed``)."""
    forge.timelines[7] = [
        {'id': 1, key: 'comment', 'created_at': '2026-11-04T09:00:00Z'},
        {key: kind, 'created_at': at},
    ]


def _later_run(forge: FakeForge, *, created: str | None = '2026-11-04T12:00:00Z', conclusion: str = 'success') -> int:
    """A newer prepare run of PR #7 (started 12:00) that attached the same honest bundle; its artifact id."""
    ((_, (_, name, data)),) = forge.artifacts.items()
    later = _prepare_run(forge.pull.head_sha, run=8, conclusion=conclusion, backend=forge.backend)
    later.update({_CREATED[forge.backend]: created, 'started_at': '2026-11-04T12:00:00Z'})
    forge.runs.append(later)
    forge.artifacts[950] = (8, name, data)
    return 950


@pytest.mark.parametrize(('key', 'kind'), [('type', 'change_target_branch'), ('event', 'base_ref_changed')])
def test_a_prepare_run_from_before_the_pr_was_retargeted_is_never_read(prepared: Prepared, key: str, kind: str) -> None:
    """Opened into a branch whose prepare workflow its author wrote, then retargeted: that run proves nothing.

    PLANTED CONTROL: a run created after the retarget is read and approved.
    """
    forge = prepared.forge
    _retarget(forge, '2026-11-04T11:00:00Z', key=key, kind=kind)
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.downloaded) == ([], [], [])
    after = _later_run(forge)
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    assert forge.downloaded == [after]


@pytest.mark.parametrize('created', ['2026-11-04T10:30:00Z', None])
def test_a_run_not_shown_created_after_the_retarget_is_never_read(prepared: Prepared, created: str | None) -> None:
    """Queued before the retarget yet STARTED after it -- or with no creation time at all: never approved."""
    forge = prepared.forge
    _retarget(forge, '2026-11-04T11:00:00Z')
    _later_run(forge, created=created)
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts(), forge.downloaded) == ([], [], [], [])


def test_a_newer_run_in_flight_blocks_an_older_success(prepared: Prepared) -> None:
    """The NEWEST run decides even while it runs: never fall through to an older concluded one.

    PLANTED CONTROL: once it concludes success, it is read.
    """
    forge = prepared.forge
    after = _later_run(forge, conclusion='')
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.downloaded) == ([], [], [])
    forge.runs[-1]['conclusion'] = 'success'
    said, _ = _judged(forge, _findings(None))
    assert (said, forge.downloaded) == ([f'#7 {forge.pull.head_sha[:12]}: APPROVED'], [after])


@pytest.mark.parametrize('timeline', [None, [{'type': 'change_target_branch', 'created_at': 'yesterday'}]])
def test_a_timeline_that_cannot_be_read_approves_nothing(
    prepared: Prepared, timeline: list[dict[str, Any]] | None
) -> None:
    forge = prepared.forge
    forge.timelines[7] = timeline
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.verdicts(), forge.downloaded) == ([], [], [])
    assert 'not judged' in said[0] or 'retried' in said[0]


def test_a_prepare_run_still_going_decides_nothing(prepared: Prepared) -> None:
    prepared.forge.runs[0]['conclusion'] = ''
    assert _judged(prepared.forge, _findings(None)) == ([], [])


@pytest.mark.parametrize(
    'run',
    [
        {'event': 'pull_request'},  # a PR-head workflow
        {'workflow': 'ci.yml'},  # the base's, but another workflow
        {'number': 8},  # the same head prepared for ANOTHER pull request, into a branch its author controls
    ],
)
def test_an_artifact_of_any_run_but_the_bases_prepare_run_of_this_pull_is_never_read(
    prepared: Prepared, run: dict[str, Any]
) -> None:
    forge = prepared.forge
    head, ident = forge.pull.head_sha, forge.runs[0]['id']
    forge.runs[0] = _prepare_run(head, run=ident, conclusion='success', backend=forge.backend, **run)
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts(), forge.downloaded) == ([], [], [], [])


@pytest.mark.parametrize(
    'pulls',
    [
        [],  # a fork's run: GitHub lists no pull request on it, so nothing binds it to this one
        [7, 8],  # a run naming two pull requests is bound to neither
    ],
)
def test_a_github_run_that_does_not_name_this_pull_alone_is_never_read(on_github: Prepared, pulls: list[int]) -> None:
    """GitHub names a run's pull requests apart from its path; only ``[this one]`` binds it.

    PLANTED CONTROL: the honest run names ``[7]`` and is approved.
    """
    forge = on_github.forge
    head, ident = forge.pull.head_sha, forge.runs[0]['id']
    forge.runs[0] = _prepare_run(head, run=ident, conclusion='success', backend=GITHUB, pulls=pulls)
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts(), forge.downloaded) == ([], [], [], [])
    forge.runs[0] = _prepare_run(head, run=ident, conclusion='success', backend=GITHUB)
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {head[:12]}: APPROVED']


def test_the_runs_are_listed_with_each_forges_own_page_size(prepared: Prepared) -> None:
    forge = prepared.forge
    _judged(forge, _findings(None))
    (listing,) = [path for path in forge.asked if path.startswith(f'{forge.repo}/actions/runs?')]
    assert f'&{forge.backend.page_param}=' in listing


def test_a_bad_artifact_of_the_honest_run_is_request_changes(prepared: Prepared) -> None:
    forge = prepared.forge
    ((ident, (run, name, _)),) = forge.artifacts.items()
    forge.artifacts[ident] = (run, name, zipped({'other.txt': b'{}'}))
    said, seen = _judged(forge, _findings(None))
    assert seen == []
    (review,) = forge.verdicts()
    assert (review['event'], fp.BUNDLE_FILE in review['body']) == ('REQUEST_CHANGES', True)
    assert said[0].endswith('REQUEST_CHANGES')


def test_a_dismissed_verdict_is_judged_again(prepared: Prepared) -> None:
    forge = prepared.forge
    _judged(forge, _findings(None))
    forge.verdicts()[0]['dismissed'] = True
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_the_reviewer_is_handed_no_disposals(prepared: Prepared) -> None:
    """Nothing is disposed in a one-shot review (user ruling 2026-11-06): the disposed file is empty."""
    read: list[dict[str, str]] = []
    _judged(prepared.forge, _findings(None), read=read)
    assert json.loads(read[0]['disposed']) == {'disposed': []}


@pytest.mark.parametrize(('security', 'event'), [(False, 'APPROVED'), (True, 'REQUEST_CHANGES')])
def test_a_high_finding_is_advice_and_a_security_finding_requests_changes(
    prepared: Prepared, *, security: bool, event: str
) -> None:
    """User ruling 2026-11-06: a HIGH finding is advice -- APPROVED, the finding listed as advice.

    PLANTED CONTROL: the same finding tagged security is REQUEST_CHANGES.
    """
    _judged(prepared.forge, _findings('HIGH', security=security))
    (review,) = prepared.forge.verdicts()
    assert review['state'] == event
    assert 'F-0123456789ab' in review['body']
    assert ('Advice' in review['body']) is not security


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
def test_a_preparer_ref_not_bound_to_the_head_and_digest_is_never_fetched(hosted: Prepared, key: str) -> None:
    forge = hosted.forge
    (status,) = forge.statuses[forge.pull.head_sha]
    ref = fp.ref_of_pointer(status['target_url'])
    digest = status['description'].removeprefix('sha256:')[:16]
    forged = Ref(ref.backend, key.format(other='c' * 12, digest=digest), ref.bytes, ref.sha256)
    status['target_url'] = fp.pointer(forged)
    _judged(forge, _findings(None))
    assert hosted.fetched == []
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
    """PR #6 (listed first) was prepared by its trusted run into an artifact with no bundle.json; *diff* its diff."""
    forge = prepared.forge
    forge.others.append(PullRequest(6, 'p', 'open', '', 'u', 'a', 'pr/p', 'main', head_sha=_POISONED))
    forge.runs.append(_prepare_run(_POISONED, number=6, conclusion='success', backend=forge.backend))
    forge.attach(6, fp.ARTIFACT, {'other.txt': b'{}'})
    if diff is not None:
        forge.diffs[6] = diff


def test_a_corrupt_artifact_is_request_changes_and_the_next_pr_is_still_judged(prepared: Prepared) -> None:
    _poison(prepared, diff='')
    said, _ = _judged(prepared.forge, _findings(None))
    assert said == [f'#6 {_POISONED[:12]}: REQUEST_CHANGES', f'#7 {prepared.forge.pull.head_sha[:12]}: APPROVED']
    (review,) = prepared.forge.verdicts(6)
    assert fp.BUNDLE_FILE in review['body']


def test_a_read_failure_posts_nothing_and_the_next_pr_is_still_judged(prepared: Prepared) -> None:
    _poison(prepared, diff=None)  # the forge serves no diff of #6: a read failure
    forge = prepared.forge
    ((ident, (run, name, _)),) = [(k, v) for k, v in forge.artifacts.items() if v[0] == 6]
    forge.artifacts[ident] = (run, name, forge.artifacts[900][2])  # a readable bundle, so the diff is what fails
    said, _ = _judged(forge, _findings(None))
    assert said[0].startswith(f'#6 {_POISONED[:12]}')
    assert said[-1] == f'#7 {forge.pull.head_sha[:12]}: APPROVED'
    assert forge.verdicts(6) == []


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


@pytest.mark.parametrize('login', [ACTIONS_BOT, ''])
def test_no_identity_an_actions_job_posts_as_may_be_a_preparer(login: str) -> None:
    with pytest.raises(ValueError, match='preparers'):
        review_from(_JUDGED + f'preparers = ["{login}"]\n', 'x')


def test_a_pointer_round_trips_and_anything_else_is_refused() -> None:
    ref = Ref('folder', 'r/2026/11/03/x.tar.gz', 10, 'ab' * 32)
    assert fp.ref_of_pointer(fp.pointer(ref)) == ref
    for bad in ('https://x/y', 'artefact:?backend=folder'):
        with pytest.raises(BundleRefused, match='Ref'):
            fp.ref_of_pointer(bad)


def test_a_pointer_only_another_login_posted_is_ignored(hosted: Prepared) -> None:
    """PLANTED CONTROL: the same head pointed at by the declared preparer is approved below."""
    forge = hosted.forge
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': 'mallory'}
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts()) == ([], [], [])


def test_a_null_creator_pointer_is_never_read(hosted: Prepared) -> None:
    """A Gitea Actions job -- a PR-head one included -- posts with a null creator: no pointer of it is a source."""
    forge = hosted.forge
    forge.statuses[forge.pull.head_sha][0]['creator'] = None
    forge.runs.append(_prepare_run(forge.pull.head_sha, conclusion='success'))  # even beside an honest run
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts()) == ([], [], [])


def test_a_github_bot_pointer_is_never_read(hosted: Prepared) -> None:
    """On GitHub a same-repository branch's workflow posts as the Actions bot, which is never a declared preparer."""
    forge = hosted.forge
    forge.backend = GITHUB
    forge.statuses[forge.pull.head_sha][0]['creator'] = {'login': ACTIONS_BOT}
    said, seen = _judged(forge, _findings(None))
    assert (said, seen, forge.verdicts()) == ([], [], [])


def test_a_declared_preparer_s_pointer_is_read(hosted: Prepared) -> None:
    said, _ = _judged(hosted.forge, _findings(None))
    assert said == [f'#7 {hosted.forge.pull.head_sha[:12]}: APPROVED']


def test_a_forged_newer_pointer_neither_griefs_nor_shadows_the_preparer_s(hosted: Prepared) -> None:
    forge = hosted.forge
    (honest,) = forge.statuses[forge.pull.head_sha]
    forge.poster = None
    forge.call('POST', f'{forge.repo}/statuses/{forge.pull.head_sha}', {
        **{k: honest[k] for k in ('context', 'state', 'description')},
        'target_url': 'artefact:?backend=folder&ref=forged&bytes=1&sha256=' + '0' * 64,
    })  # fmt: skip
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_a_host_that_is_not_the_declared_judge_judges_nothing(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.login = 'someone-else'
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.verdicts()) == ([], [])
    assert 'judge_login' in said[0]


def test_prepare_stores_where_the_base_declares_never_where_the_head_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head is DATA: its ``[tool.lab_commons.artefacts]`` cannot choose the store the bundle goes to.

    PLANTED CONTROL: the head declares a folder store; the base declares none, so the forge's store is used.
    """
    root, base, _ = _repo(tmp_path)
    head_toml = (
        _JUDGE_TOML + f'\n[tool.lab_commons.artefacts]\nbackend = "folder"\nremote = "{tmp_path.as_posix()}/x"\n'
    )
    (root / 'pyproject.toml').write_text(head_toml, encoding='utf-8')
    run_git(root, 'commit', '-q', '-am', 'the head names its own store')
    head = git_out(root, 'rev-parse', 'HEAD')
    configs: list[Config] = []
    prepared = _prepared(tmp_path, monkeypatch, root, base, head, configs=configs, hosted=True)
    assert configs == [Config()]
    assert fp.ref_of_pointer(prepared.forge.statuses[head][0]['target_url']).backend == 'folder'


_APP = App(5619495, 'motronics-review')


@pytest.fixture(autouse=True)
def _apps_of_the_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fake forge says which App it is through ``app``, as an :class:`~dev_lab.dev.forgeapp.AppClient` does."""
    monkeypatch.setattr(fb, 'app_of', lambda client: client.app)


def _as_app(forge: FakeForge, *, declared: int = _APP.app_id) -> FakeForge:
    """*forge* (GitHub) judged by the App: the manifest declares judge_app, the client holds the App's token."""
    forge.manifest = forge.manifest.replace('judge_login = "review-bot"', f'judge_app = {declared}')
    forge.app, forge.login = _APP, _APP.login
    return forge


def test_an_app_judge_posts_its_verdict_as_a_check_run_never_a_review(on_github: Prepared) -> None:
    forge = _as_app(on_github.forge)
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (run,) = forge.checks[forge.pull.head_sha]
    assert (run['name'], run['conclusion'], run['app']['id']) == (JUDGE_CHECK, 'success', _APP.app_id)
    assert run['output']['title'] == 'approved'
    assert forge.verdicts() == []
    assert _judged(forge, _findings(None)) == ([], [])  # idempotent per head


def test_an_app_judge_concludes_failure_on_a_security_finding(on_github: Prepared) -> None:
    forge = _as_app(on_github.forge)
    _judged(forge, _findings('LOW', security=True))
    (run,) = forge.checks[forge.pull.head_sha]
    assert run['conclusion'] == 'failure'
    assert 'Security' in run['output']['summary']


def test_a_same_named_run_from_another_app_is_not_this_judges_verdict(on_github: Prepared) -> None:
    """PLANTED CONTROL: the head carries an impostor's review/judge success; the App judges it all the same."""
    forge = _as_app(on_github.forge)
    impostor = {'id': 9, 'name': JUDGE_CHECK, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 1}}
    forge.checks[forge.pull.head_sha] = [{**impostor, 'head_sha': forge.pull.head_sha}]
    said, _ = _judged(forge, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_an_app_that_is_not_the_declared_one_judges_nothing(on_github: Prepared) -> None:
    forge = _as_app(on_github.forge, declared=1)
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.checks) == ([], {})
    assert 'judge_app = 1; this host is App 5619495' in said[0]


def test_a_login_declaration_is_never_judged_by_an_app(on_github: Prepared) -> None:
    forge = on_github.forge
    forge.app = _APP
    said, seen = _judged(forge, _findings(None))
    assert (seen, forge.checks, forge.verdicts()) == ([], {}, [])
    assert 'judge_login' in said[0]


@pytest.mark.parametrize('half', [['--app-id', '5619495'], ['--app-key-file', 'k.pem']])
def test_the_judge_cli_never_takes_half_an_app(tmp_path: Path, half: list[str]) -> None:
    assert fb.main(['judge', '--url', 'https://github.com/o/r', *half], cwd=tmp_path) == 2
