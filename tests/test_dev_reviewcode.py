"""reviewcode: the one code classification, and the review job's first step that settles a PR holding none."""

from __future__ import annotations

import ast
import io
import sys
from pathlib import Path
from typing import Any

import pytest

from dev_lab.dev import forgereview_scope, reviewcode
from dev_lab.dev.forgecontexts import REVIEW_CONTEXT
from dev_lab.dev.reviewcode import ONLY_GENERATED, main, nothing_to_review, settle

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
    assert 'refusé' in text.getvalue()
    assert (tmp_path / 'out').read_text(encoding='utf-8') == 'settled=false\n'
