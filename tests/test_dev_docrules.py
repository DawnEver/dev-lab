"""The doc-rules hook quotes the family's rules verbatim before a doc edit, and stays silent on code."""

from __future__ import annotations

import io
import json

import pytest

from dev_lab.dev import docrules
from dev_lab.dev.principles import PRINCIPLES
from dev_lab.dev.rules import RULES


def _run(tool: str, path: str, capsys: pytest.CaptureFixture[str]) -> str:
    payload = {'tool_name': tool, 'tool_input': {'file_path': path}}
    assert docrules.main([], stdin=io.StringIO(json.dumps(payload))) == 0
    return capsys.readouterr().out


@pytest.mark.parametrize(
    'path', ['docs-src/dev/gate.md', 'C:\\repo\\.claude\\rules\\x.md', 'AGENTS.md', 'a/b/notes.md']
)
def test_a_doc_edit_receives_every_quoted_statement_verbatim(path: str, capsys: pytest.CaptureFixture[str]) -> None:
    context = json.loads(_run('Edit', path, capsys))['hookSpecificOutput']['additionalContext']
    homes = {rule.id: rule.statement for rule in RULES} | {one.id: one.statement for one in PRINCIPLES}
    for rid in (*docrules.DOC_RULES, *docrules.DOC_PRINCIPLES):
        assert f'- {rid}: {homes[rid]}' in context


@pytest.mark.parametrize(('tool', 'path'), [('Edit', 'src/pkg/a.py'), ('Read', 'README.md'), ('Write', '')])
def test_code_a_read_or_no_path_gets_nothing(tool: str, path: str, capsys: pytest.CaptureFixture[str]) -> None:
    """Planted control: the hook must be able to stay silent, or it is noise."""
    assert _run(tool, path, capsys) == ''


def test_an_unreadable_payload_never_blocks(capsys: pytest.CaptureFixture[str]) -> None:
    assert docrules.main([], stdin=io.StringIO('not json')) == 0
    assert capsys.readouterr().out == ''
