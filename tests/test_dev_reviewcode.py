"""reviewcode: the one code classification, and the review job's first step that settles a PR holding none."""

from __future__ import annotations

import ast
import io
import sys
import urllib.error
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import forgefailure, forgereview_scope, reviewcode
from dev_lab.dev.forgecontexts import REVIEW_CONTEXT
from dev_lab.dev.netverb import DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S, Diagnosis, is_retryable
from dev_lab.dev.reviewcode import ONLY_GENERATED, forge_call, main, nothing_to_review, settle

API = 'http://forge/api/v1/repos/o/r'
HEAD = 'a' * 40
POLICY = '[tool.dev_lab.integrator]\nintegration = "integrate/main"\n'


def test_the_module_runs_on_a_bare_interpreter() -> None:
    """The job fetches this one file and runs it before any install: it imports the stdlib alone."""
    tree = ast.parse(Path(reviewcode.__file__).read_text(encoding='utf-8'))
    roots = {
        (node.module if isinstance(node, ast.ImportFrom) else alias.name).split('.')[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert roots - {'__future__'} <= sys.stdlib_module_names, roots


def test_the_review_and_the_first_step_share_one_classification() -> None:
    assert forgereview_scope.is_code is reviewcode.is_code
    assert reviewcode.REVIEW_CONTEXT == REVIEW_CONTEXT


def test_nothing_to_review_reads_the_declared_globs() -> None:
    assert nothing_to_review(['.claude/memory/2026/x.md', 'docs/a.md'], '')
    assert not nothing_to_review(['.claude/memory/x.md', 'src/a.py'], '')
    assert not nothing_to_review([], ''), 'an unread file list never settles a head'
    assert not nothing_to_review(['docs/a.md'], '[tool.dev_lab.review]\ncode = ["**/*.md"]\n')


class Forge:
    """The forge API one review job reads, answering by URL; the posts it took."""

    def __init__(self, files: list[str], *, draft: bool = False, base: str = 'integrate/main') -> None:
        """A PR into *base* changing *files*."""
        self.files = files
        self.posted: list[tuple[str, dict[str, Any]]] = []
        self.replies: dict[str, object] = {
            f'{API}/pulls/7': {'state': 'open', 'draft': draft, 'head': {'sha': HEAD}, 'base': {'ref': base}},
            API: {'default_branch': 'main'},
            f'{API}/raw/pyproject.toml?ref=main': POLICY,
            f'{API}/raw/pyproject.toml?ref=integrate/main': '',
            f'{API}/actions/runs/99': {'html_url': 'http://forge/o/r/actions/runs/5'},
        }

    def __call__(self, method: str, url: str, body: dict[str, Any] | None) -> object:
        """The reply to *method* *url*."""
        if method == 'POST':
            self.posted.append((url, body or {}))
            return {}
        if url.startswith(f'{API}/pulls/7/files?limit=50&page='):
            page = int(url.rpartition('=')[2])
            return [{'filename': f} for f in self.files[(page - 1) * 50 : page * 50]]
        return self.replies[url]


def test_a_pr_with_no_code_is_posted_the_review_s_own_success_naming_its_run() -> None:
    forge = Forge([f'.claude/memory/{i}.md' for i in range(120)])
    assert settle(forge, API, 7, HEAD, '99')
    assert forge.posted == [(f'{API}/statuses/{HEAD}', {
        'context': REVIEW_CONTEXT, 'state': 'success', 'description': ONLY_GENERATED,
        'target_url': 'http://forge/o/r/actions/runs/5'})]  # fmt: skip


def test_code_on_any_page_a_draft_or_another_base_settles_nothing() -> None:
    """PLANTED CONTROL: one code file on the third page is read, so the review runs."""
    for forge in (
        Forge([f'.claude/memory/{i}.md' for i in range(120)] + ['src/a.py']),
        Forge(['.claude/memory/x.md'], draft=True),
        Forge(['.claude/memory/x.md'], base='lane/x'),
    ):
        assert settle(forge, API, 7, HEAD, '99') is None
        assert forge.posted == []
    assert settle(Forge(['.claude/memory/x.md']), API, 7, 'b' * 40, '99') is None, 'a superseded head'


def test_the_step_never_fails_and_tells_later_steps(tmp_path: Path) -> None:
    out = tmp_path / 'out'
    env = {'FORGE_URL': 'http://forge', 'GITHUB_REPOSITORY': 'o/r', 'GITHUB_TOKEN': 't', 'PR_NUMBER': '7',
           'HEAD_SHA': HEAD, 'GITHUB_RUN_ID': '99', 'GITHUB_OUTPUT': str(out)}  # fmt: skip
    assert main(env, Forge(['.claude/memory/x.md'])) == 0
    assert main(env, Forge(['src/a.py'])) == 0

    def broken(*_: object) -> object:
        msg = 'refused'
        raise OSError(msg)

    assert main(env, broken) == 0
    assert out.read_text(encoding='utf-8').splitlines() == ['settled=true', 'settled=false', 'settled=false']


def _env(out: Path) -> dict[str, str]:
    return {'FORGE_URL': 'http://forge', 'GITHUB_REPOSITORY': 'o/r', 'GITHUB_TOKEN': 't', 'PR_NUMBER': '7',
            'HEAD_SHA': HEAD, 'GITHUB_RUN_ID': '99', 'GITHUB_OUTPUT': str(out)}  # fmt: skip


def _refused(*_: object) -> object:
    msg = 'refusé'
    raise OSError(msg)


def test_a_non_ascii_reason_reaches_an_ascii_stdout_as_utf8(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(raw, encoding='ascii'))
    assert main(_env(tmp_path / 'out'), _refused) == 0
    assert 'refusé'.encode() in raw.getvalue()


def test_a_stdout_with_no_buffer_still_returns_0_and_writes_the_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', text)
    assert main(_env(tmp_path / 'out'), _refused) == 0
    assert text.getvalue() == '', 'a text write is what ONE-WRITER-OWNS-THE-CONSOLE refuses'
    assert (tmp_path / 'out').read_text(encoding='utf-8') == 'settled=false\n'


def _message(headers: dict[str, str]) -> Message:
    out = Message()
    for name, value in headers.items():
        out[name] = value
    return out


class _Opener:
    """``urlopen`` answering a scripted sequence: an int is that HTTP status refused, bytes the answer."""

    def __init__(self, *script: object, headers: dict[str, str] | None = None) -> None:
        self.script, self.headers, self.opened = list(script), headers or {}, 0

    def __call__(self, request: object, **_: object) -> io.BytesIO:
        self.opened += 1
        step = self.script.pop(0)
        if isinstance(step, OSError):
            raise step
        if isinstance(step, int):
            msg = 'http://forge/x'
            raise urllib.error.HTTPError(msg, step, 'no', _message(self.headers), io.BytesIO(b'{}'))
        return io.BytesIO(bytes(step))  # a scripted answer


def _call(opener: _Opener, sleeps: list[float]) -> reviewcode.Call:
    return forge_call('t', opener=opener, sleep=sleeps.append)


def test_a_transient_failure_is_retried_with_backoff_then_answers() -> None:
    sleeps: list[float] = []
    opener = _Opener(503, OSError('reset'), b'{"a": 1}')
    assert _call(opener, sleeps)('GET', 'http://forge/api/v1/x', None) == {'a': 1}
    assert sleeps == [reviewcode.BACKOFF_S, reviewcode.BACKOFF_S]


def test_a_refusal_is_not_retried_and_the_attempts_are_bounded() -> None:
    """PLANTED CONTROL: a 404 is final after one attempt; a forge down for good stops at ATTEMPTS."""
    sleeps: list[float] = []
    with pytest.raises(OSError, match='404'):
        _call(_Opener(404), sleeps)('GET', 'http://forge/api/v1/x', None)
    assert sleeps == []
    down = _Opener(*[502] * 5)
    with pytest.raises(OSError, match='502'):
        _call(down, sleeps)('GET', 'http://forge/api/v1/x', None)
    assert down.opened == reviewcode.ATTEMPTS


def test_a_rate_limit_waits_what_the_forge_names_and_past_the_cap_is_reported() -> None:
    sleeps: list[float] = []
    limited = _Opener(429, b'[]', headers={'Retry-After': '7'})
    assert _call(limited, sleeps)('GET', 'http://forge/api/v1/x', None) == []
    assert sleeps == [7.0]
    with pytest.raises(OSError, match='rate limit'):
        _call(_Opener(429, headers={'Retry-After': '3600'}), sleeps)('GET', 'http://forge/api/v1/x', None)


def test_a_refused_credential_stops_and_is_reported_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The settle never fails the job, but a refused job token is a loud annotation naming the forge host."""
    sleeps: list[float] = []
    opener = _Opener(401, 401)
    with pytest.raises(reviewcode.CredentialRefused, match=r'forge\.example'):
        forge_call('t', opener=opener, sleep=sleeps.append)('GET', 'https://forge.example/api/v1/x', None)
    assert (opener.opened, sleeps) == (1, [])
    raw = io.BytesIO()
    monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(raw, encoding='utf-8'))

    def refused(*_: object) -> object:
        msg = 'https://forge.example/api/v1/x'
        raise reviewcode.CredentialRefused(msg)

    assert main(_env(tmp_path / 'out'), refused) == 0
    said = raw.getvalue().decode()
    assert said.startswith('::error'), said
    assert 'forge.example' in said
    assert (tmp_path / 'out').read_text(encoding='utf-8') == 'settled=false\n'


@pytest.mark.parametrize(
    ('status', 'text', 'headers'),
    [(0, 'reset', {}), (404, '', {}), (408, '', {}), (422, '', {}), (429, '', {}), (403, 'API rate limit exceeded', {}),
     (403, '', {'X-RateLimit-Remaining': '0'}), (403, 'forbidden', {}), (500, '', {}), (502, '', {}), (503, '', {})],
)  # fmt: skip
def test_the_bare_loop_decides_as_the_family_loop_does(status: int, text: str, headers: dict[str, str]) -> None:
    """Reviewcode runs before any install, so it cannot import forgefailure: this pins its decision to that one."""
    family = forgefailure.diagnose(status, text, headers)
    mine = reviewcode.verdict(status, text, headers)
    if family is Diagnosis.RATE_LIMITED:
        assert mine == 'wait'
    else:
        assert (mine == 'retry') is is_retryable(family), (mine, family)
    assert (reviewcode.ATTEMPTS, reviewcode.BACKOFF_S) == (DEFAULT_ATTEMPTS, DEFAULT_BACKOFF_S)
    assert reviewcode.RATE_WAIT_CAP_S == forgefailure.RATE_WAIT_CAP_S
    assert reviewcode.verdict(401, '', {}) == 'credential'
