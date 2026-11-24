"""rulesinject: a harness that does not load .claude/rules itself gets them at SessionStart; Claude Code does not."""

from __future__ import annotations

import io
import json
from typing import TYPE_CHECKING

from dev_lab.dev import rulesinject

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _rules(root: Path) -> None:
    (root / '.claude/rules/rem').mkdir(parents=True)
    (root / '.claude/rules/b.md').write_text('# B\n', encoding='utf-8')
    (root / '.claude/rules/a.md').write_text('# A\n\n', encoding='utf-8')
    (root / '.claude/rules/notes.txt').write_text('not a page', encoding='utf-8')


def test_every_page_sorted_and_headed(tmp_path: Path) -> None:
    _rules(tmp_path)
    assert (
        rulesinject.rules_context(tmp_path)
        == 'Contents of .claude/rules/a.md:\n\n# A\n\nContents of .claude/rules/b.md:\n\n# B'
    )
    assert rulesinject.rules_context(tmp_path / 'none') == ''


def _hook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], root: Path, harness: str, source: str
) -> str:
    for key in ('CLAUDE_CODE_SESSION_ID', 'CODEX_THREAD_ID', 'CODEX_SESSION_ID', 'CLAUDE_PROJECT_DIR'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(harness, 'abc')
    monkeypatch.setattr('sys.stdin', io.StringIO(json.dumps({'cwd': str(root), 'source': source})))
    assert rulesinject.main([]) == 0
    return capsys.readouterr().out


def test_codex_gets_the_rules_and_claude_code_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _rules(tmp_path)
    assert '# A' in _hook(monkeypatch, capsys, tmp_path, 'CODEX_THREAD_ID', 'startup')
    assert _hook(monkeypatch, capsys, tmp_path, 'CLAUDE_CODE_SESSION_ID', 'startup') == '', 'it loads them itself'
    assert _hook(monkeypatch, capsys, tmp_path, 'CODEX_THREAD_ID', 'resume') == '', 'a resumed context holds them'
