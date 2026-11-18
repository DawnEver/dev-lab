"""The bundle review: the judge fetches each due head itself, prepares its bundle, verifies, reviews, posts once.

The judge trusts nothing the producer wrote that it can read or derive from the forge (D3), and since D77 no
producer writes anything it reads: it fetches the PR head from the forge into a bare repository and builds the
bundle with the one builder. PLANTED CONTROLS: the honest head is APPROVED on both forges, and against it a tampered
forge diff, another merge base and a binary code file are each REQUEST_CHANGES; a head the forge no longer serves,
or a failure to read, posts nothing and never stops the next PR; a security finding is REQUEST_CHANGES; a head
already judged is not judged again; a judge repo is never served; a reviewer that did not run posts nothing.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from _forge_fake import git_out, run_git
from _roles_fixtures import CI_REPO, carry

from dev_lab.dev import forgereview_bundle as fb
from dev_lab.dev._forge_records import PullRequest
from dev_lab.dev._forgebackends import GITEA, GITHUB, Backend
from dev_lab.dev.forge import Forge
from dev_lab.dev.forgeapp import App
from dev_lab.dev.forgecontexts import JUDGE_CHECK
from dev_lab.dev.forgereview import review_tick
from dev_lab.dev.forgereview_claim import DUE
from dev_lab.dev.forgereview_declared import FAMILY_BUNDLE, Review, command_for, review_from
from dev_lab.dev.platformparts import REVIEW_CONTEXT

_JUDGED = '[tool.dev_lab.review]\njudge_login = "review-bot"\n'
_JUDGE_TOML = '[tool.dev_lab.integrator]\nintegration = "main"\n' + _JUDGED
_RUNTIMES = {'ai_lab': {'python': 'py'}}
_POISONED = 'b' * 40
#: Each forge as the judge's client reaches it: its host, and its repository's API collection.
_FORGES = {
    GITEA: (Forge('forge.example.org', 'o', 'r'), '/api/v1/repos/o/r'),
    GITHUB: (Forge('github.com', 'o', 'r'), '/repos/o/r'),
}


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


@dataclass
class FakeForge:
    """One repository's API as the judge sees it: statuses, reviews, check runs, the manifest, PRs and their diffs."""

    pull: PullRequest
    diffs: dict[int, str]
    merge_base: str
    manifest: str = _JUDGE_TOML
    login: str = 'review-bot'
    others: list[PullRequest] = field(default_factory=list)  # listed BEFORE pull
    statuses: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    reviews: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
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

    def call(self, method: str, path: str, body: dict[str, Any] | None = None, durable: object = None) -> Any:  # noqa: ANN401
        del durable
        path = path.partition('?')[0]
        return self._post(path, body or {}) if method == 'POST' else self._get(path)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if path.endswith('/check-runs'):
            assert self.app is not None
            runs = self.checks.setdefault(body['head_sha'], [])
            runs.append({'id': len(runs) + 1, 'app': {'id': self.app.app_id, 'slug': self.app.slug}, **body})
            return runs[-1]
        number = int(path.split('/')[-2])
        rows = self.reviews.setdefault(number, [])
        state = {'APPROVE': 'APPROVED'}.get(body['event'], body['event'])  # GitHub's event names its verb
        rows.append({'id': len(rows) + 1, 'user': {'login': self.login}, 'state': state, **body})
        return rows[-1]

    def _get(self, path: str) -> Any:  # noqa: ANN401
        manifest = {'content': base64.b64encode(self.manifest.encode()).decode()}
        answers: dict[str, Any] = {
            self.repo: {'default_branch': 'main'},
            f'{self.repo}/contents/pyproject.toml': manifest,
            f'{self.repo}/pulls': [_raw(one) for one in self._pulls().values()],
        }
        for number, one in self._pulls().items():
            answers[f'{self.repo}/pulls/{number}'] = {'merge_base': self.merge_base}
            compare = f'{self.repo}/compare/{one.base}...{one.head_sha}'
            answers[compare] = {'merge_base_commit': {'sha': self.merge_base}}
            answers[f'{self.repo}/pulls/{number}/reviews'] = list(self.reviews.get(number, []))
            answers[f'{self.repo}/issues/{number}/comments'] = []
            answers[f'{self.repo}/statuses/{one.head_sha}'] = list(self.statuses.get(one.head_sha, []))
            answers[f'{self.repo}/commits/{one.head_sha}/statuses'] = list(self.statuses.get(one.head_sha, []))
            answers[f'{self.repo}/commits/{one.head_sha}/check-runs'] = {
                'check_runs': self.checks.get(one.head_sha, [])
            }
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
    """The forge's repository (``remote.git``) with integration ``main``, and a clone whose PR head is ``pr/x``."""
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
    """A PR #7 the forge serves (``refs/pull/7/head``), and the fetch the judge reaches the forge's git with."""

    forge: FakeForge
    root: Path
    fetch: fb.Fetch


def _prepared(root: Path, base: str, head: str, *, backend: Backend = GITEA) -> Prepared:
    """PR #7 on *backend*: its head published under ``refs/pull/7/head``, as both forges serve a PR's head."""
    run_git(root, 'push', '-q', 'origin', f'{head}:refs/pull/7/head')
    pull = PullRequest(7, 't', 'open', 'the body', 'u', 'a', 'pr/x', 'main', head_sha=head)
    diffs = {7: git_out(root, 'diff', '--full-index', base, head)}
    where, repo = _FORGES[backend]
    forge = FakeForge(pull, diffs, base, forge=where, backend=backend, repo=repo)
    return Prepared(forge, root, fb.fetch_from((root.parent / 'remote.git').as_uri()))


@pytest.fixture(params=[GITEA, GITHUB], ids=['gitea', 'github'])
def prepared(tmp_path: Path, request: pytest.FixtureRequest) -> Prepared:
    """A PR head the forge serves, on each forge."""
    return _prepared(*_repo(tmp_path), backend=request.param)


@pytest.fixture
def on_github(tmp_path: Path) -> Prepared:
    """A PR head the forge serves, on GitHub."""
    return _prepared(*_repo(tmp_path), backend=GITHUB)


def _judged(
    prepared: Prepared, out: str, *, read: list[dict[str, str]] | None = None
) -> tuple[list[str], list[tuple[str, ...]]]:
    forge = prepared.forge
    seen: list[tuple[str, ...]] = []

    def run(argv: tuple[str, ...], _where: Path, env: dict[str, str]) -> str:
        seen.append(tuple(argv))
        tree = Path(argv[argv.index('--bundle') + 1])
        disposed = Path(argv[argv.index('--disposed') + 1]).read_text(encoding='utf-8')
        if read is not None:
            read.append({'diff': (tree / 'diff.patch').read_text(encoding='utf-8'), 'disposed': disposed, **env})
        return out

    for one in forge._pulls().values():  # the merge decision called each head due: the review runs last
        rows = forge.statuses.setdefault(one.head_sha, [])
        if not any(row['context'] == REVIEW_CONTEXT for row in rows):
            rows.append({'id': len(rows) + 1, 'creator': None, 'context': REVIEW_CONTEXT, 'state': 'pending',
                         'description': DUE, 'target_url': ''})  # fmt: skip
    return fb.judge_pending(forge, runtimes=_RUNTIMES, fetch=prepared.fetch, run=run), seen  # type: ignore[arg-type]


def test_the_judge_approves_a_clean_head_once_reading_the_forges_diff(prepared: Prepared) -> None:
    forge, read = prepared.forge, []
    said, seen = _judged(prepared, _findings(None), read=read)
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (review,) = forge.verdicts()
    assert (review['state'], review['commit_id']) == ('APPROVED', forge.pull.head_sha)
    (argv,) = seen
    assert argv[:4] == ('py', '-m', 'ai_lab.review', '--bundle')
    assert '--pr-body' in argv
    assert not Path(argv[4]).exists()  # the plain files lived only for the one command
    assert read[0]['diff'] == forge.diff  # the FORGE's diff, never the producer's
    assert 'GIT_DIR' in read[0]  # no repository reachable through git's discovery
    assert _judged(prepared, _findings(None)) == ([], [])  # idempotent per head: nothing judged again


def test_a_dismissed_verdict_is_judged_again(prepared: Prepared) -> None:
    forge = prepared.forge
    _judged(prepared, _findings(None))
    forge.verdicts()[0]['dismissed'] = True
    said, _ = _judged(prepared, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_the_reviewer_is_handed_no_disposals(prepared: Prepared) -> None:
    """Nothing is disposed in a one-shot review (user ruling 2026-11-06): the disposed file is empty."""
    read: list[dict[str, str]] = []
    _judged(prepared, _findings(None), read=read)
    assert json.loads(read[0]['disposed']) == {'disposed': []}


@pytest.mark.parametrize(('security', 'event'), [(False, 'APPROVED'), (True, 'REQUEST_CHANGES')])
def test_a_high_finding_is_advice_and_a_security_finding_requests_changes(
    prepared: Prepared, *, security: bool, event: str
) -> None:
    """User ruling 2026-11-06: a HIGH finding is advice -- APPROVED, the finding listed as advice.

    PLANTED CONTROL: the same finding tagged security is REQUEST_CHANGES.
    """
    _judged(prepared, _findings('HIGH', security=security))
    (review,) = prepared.forge.verdicts()
    assert review['state'] == event
    assert 'F-0123456789ab' in review['body']
    assert ('Advice' in review['body']) is not security


@pytest.mark.parametrize('statuses', [('ok', 'timeout'), ('skipped',), ('exhausted',)])
def test_a_reviewer_that_did_not_run_posts_nothing(prepared: Prepared, statuses: tuple[str, ...]) -> None:
    said, _ = _judged(prepared, _findings(None, statuses=statuses))
    assert prepared.forge.verdicts() == []
    assert 'nothing posted' in said[0]


def test_a_reviewer_that_did_not_run_is_said_with_its_reason(prepared: Prepared) -> None:
    """The line names WHY each reviewer has no findings: a host missing its keys is otherwise undiagnosable."""
    doc = json.loads(_findings(None, statuses=('ok', 'unsupported')))
    doc['reviewers'][1]['error'] = 'anthropic has no pr-review task key stored for api.anthropic.com'
    said, _ = _judged(prepared, json.dumps(doc))
    assert prepared.forge.verdicts() == []
    assert 'r1 unsupported: anthropic has no pr-review task key stored for api.anthropic.com' in said[0]


def test_a_bundle_the_forge_diff_disowns_is_refused_as_request_changes(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.diffs[7] = forge.diff.replace('kept.py', 'other.py')
    said, seen = _judged(prepared, _findings(None))
    assert seen == []  # the reviewer never read an unverified byte
    (review,) = forge.verdicts()
    assert review['event'] == 'REQUEST_CHANGES'
    assert 'refused' in review['body']
    assert said == [f'#7 {forge.pull.head_sha[:12]}: REQUEST_CHANGES']


def test_a_bundle_of_another_merge_base_is_refused(prepared: Prepared) -> None:
    prepared.forge.merge_base = 'e' * 40
    _judged(prepared, _findings(None))
    (review,) = prepared.forge.verdicts()
    assert (review['event'], 'merge base' in review['body']) == ('REQUEST_CHANGES', True)


def test_a_binary_change_to_code_is_never_approved_unread(tmp_path: Path) -> None:
    root, base, _ = _repo(tmp_path)
    (root / 'tool.py').write_bytes(b'import os\x00\nos.system("x")\n')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'hide')
    prepared = _prepared(root, base, git_out(root, 'rev-parse', 'HEAD'))
    said, seen = _judged(prepared, _findings(None))
    assert seen == []
    (review,) = prepared.forge.verdicts()
    assert (review['event'], 'tool.py' in review['body']) == ('REQUEST_CHANGES', True)
    assert 'logo.png' not in review['body']  # a binary that is not code is no finding
    assert said[0].endswith('REQUEST_CHANGES')


def test_a_failing_command_posts_nothing_and_is_retried(prepared: Prepared) -> None:
    said, _ = _judged(prepared, 'not json')
    assert prepared.forge.verdicts() == []
    assert 'retried' in said[0]


def test_a_judge_repo_is_never_served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Review bound to a host (a judge): the hpc tick reviews nothing; PLANTED CONTROL in test_dev_roles."""
    carry(monkeypatch, CI_REPO)
    review = Review(judge_login='review-bot')
    assert review_tick(tmp_path, object(), review, base='main', host='h') == ()  # type: ignore[arg-type]


def test_the_declaration_names_the_judge_and_a_bundle_command_that_reads_the_bundle() -> None:
    assert review_from(_JUDGED, 'x').judge_login == 'review-bot'
    with pytest.raises(ValueError, match='judge_app'):
        review_from('[tool.dev_lab.review]\njudge_login = "a"\njudge_app = 1\n', 'x')
    with pytest.raises(ValueError, match='where is retired: a repo declares no placement'):
        review_from('[tool.dev_lab.review]\nwhere = "judge"\n', 'x')
    with pytest.raises(ValueError, match='bundle'):
        review_from('[tool.dev_lab.review]\nbundle = ["reviewer"]\n', 'x')
    with pytest.raises(ValueError, match='redeclares'):
        review_from(f'[tool.dev_lab.review]\nbundle = {json.dumps(list(FAMILY_BUNDLE))}\n', 'x')
    argv = command_for(Review(), 'a..b', _RUNTIMES, bundle=True)
    assert argv[:5] == ['py', '-m', 'ai_lab.review', '--bundle', '{bundle}']


def test_a_host_that_is_not_the_declared_judge_judges_nothing(prepared: Prepared) -> None:
    forge = prepared.forge
    forge.login = 'someone-else'
    said, seen = _judged(prepared, _findings(None))
    assert (seen, forge.verdicts()) == ([], [])
    assert 'judge_login' in said[0]


_APP = App(5619495, 'acme-review')


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
    said, _ = _judged(prepared, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']
    (run,) = forge.checks[forge.pull.head_sha]
    assert (run['name'], run['conclusion'], run['app']['id']) == (JUDGE_CHECK, 'success', _APP.app_id)
    assert run['output']['title'] == 'approved'
    assert forge.verdicts() == []
    assert _judged(prepared, _findings(None)) == ([], [])  # idempotent per head


def test_an_app_judge_concludes_failure_on_a_security_finding(on_github: Prepared) -> None:
    forge = _as_app(on_github.forge)
    _judged(prepared, _findings('LOW', security=True))
    (run,) = forge.checks[forge.pull.head_sha]
    assert run['conclusion'] == 'failure'
    assert 'Security' in run['output']['summary']


def test_a_same_named_run_from_another_app_is_not_this_judges_verdict(on_github: Prepared) -> None:
    """PLANTED CONTROL: the head carries an impostor's review/judge success; the App judges it all the same."""
    forge = _as_app(on_github.forge)
    impostor = {'id': 9, 'name': JUDGE_CHECK, 'status': 'completed', 'conclusion': 'success', 'app': {'id': 1}}
    forge.checks[forge.pull.head_sha] = [{**impostor, 'head_sha': forge.pull.head_sha}]
    said, _ = _judged(prepared, _findings(None))
    assert said == [f'#7 {forge.pull.head_sha[:12]}: APPROVED']


def test_an_app_that_is_not_the_declared_one_judges_nothing(on_github: Prepared) -> None:
    forge = _as_app(on_github.forge, declared=1)
    said, seen = _judged(prepared, _findings(None))
    assert (seen, forge.checks) == ([], {})
    assert 'judge_app = 1; this host is App 5619495' in said[0]


def test_a_login_declaration_is_never_judged_by_an_app(on_github: Prepared) -> None:
    forge = on_github.forge
    forge.app = _APP
    said, seen = _judged(prepared, _findings(None))
    assert (seen, forge.checks, forge.verdicts()) == ([], {}, [])
    assert 'judge_login' in said[0]


@pytest.mark.parametrize('half', [['--app-id', '5619495'], ['--app-key-file', 'k.pem']])
def test_the_judge_cli_never_takes_half_an_app(tmp_path: Path, half: list[str]) -> None:
    assert fb.main(['judge', '--url', 'https://github.com/o/r', *half], cwd=tmp_path) == 2


@pytest.fixture(autouse=True)
def _judge_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """These repos' review is bound to a host (the judge): the family binds it there (planted)."""
    carry(monkeypatch, CI_REPO)


def test_the_judge_reviews_the_head_it_fetched_itself(prepared: Prepared) -> None:
    """D77: the bundle is the judge's own -- built from the head it fetched -- and nothing else was read."""
    fetched: list[int] = []

    def fetch(pull: PullRequest, where: Path) -> Path:
        fetched.append(pull.number)
        return prepared.fetch(pull, where)

    said, _ = _judged(Prepared(prepared.forge, prepared.root, fetch), _findings(None))
    assert (fetched, said) == ([7], [f'#7 {prepared.forge.pull.head_sha[:12]}: APPROVED'])


def _poison(prepared: Prepared, *, served: bool) -> None:
    """PR #6, listed first: its head the forge does not serve (*served* False), or does but serves no diff of it."""
    forge = prepared.forge
    head = _POISONED
    if served:
        root = prepared.root
        run_git(root, 'checkout', '-q', '-b', 'pr/p', 'main')
        (root / 'p.py').write_text('p = 1\n', encoding='utf-8')
        run_git(root, 'add', '.')
        run_git(root, 'commit', '-q', '-m', 'p')
        head = git_out(root, 'rev-parse', 'HEAD')
        run_git(root, 'push', '-q', 'origin', f'{head}:refs/pull/6/head')
    forge.others.append(PullRequest(6, 'p', 'open', '', 'u', 'a', 'pr/p', 'main', head_sha=head))


@pytest.mark.parametrize('served', [False, True], ids=['head-not-served', 'diff-not-served'])
def test_a_read_failure_posts_nothing_and_the_next_pr_is_still_judged(prepared: Prepared, *, served: bool) -> None:
    _poison(prepared, served=served)
    forge = prepared.forge
    said, _ = _judged(prepared, _findings(None))
    assert 'retried' in said[0]
    assert said[0].startswith('#6 ')
    assert said[-1] == f'#7 {forge.pull.head_sha[:12]}: APPROVED'
    assert forge.verdicts(6) == []


def test_a_head_that_moved_after_the_listing_is_not_judged(prepared: Prepared) -> None:
    """PLANTED CONTROL: the forge now serves another head for #7 -- the judge reviews nothing it did not list."""
    root = prepared.root
    (root / 'later.py').write_text('l = 1\n', encoding='utf-8')
    run_git(root, 'add', '.')
    run_git(root, 'commit', '-q', '-m', 'later')
    run_git(root, 'push', '-q', '-f', 'origin', 'HEAD:refs/pull/7/head')
    said, seen = _judged(prepared, _findings(None))
    assert (seen, prepared.forge.verdicts()) == ([], [])
    assert 'moved' in said[0]
