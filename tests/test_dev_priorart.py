"""PRIOR-ART-FIRST: a NEW product module named like a tracked one is refused until it cites that prior art."""

from __future__ import annotations

import io
import json
from pathlib import Path

from _forge_fake import run_git

from dev_lab.dev import codeplace
from dev_lab.dev.codeplace import main
from dev_lab.dev.priorart import prior_art, refuse_new_module, uncited

_SRC = 'src/'
_TRACKED = ('src/pkg/alpha/assembly.py', 'src/pkg/__init__.py', 'src/pkg/alpha/__init__.py', 'tests/test_x.py')


def test_a_new_module_named_like_a_tracked_one_finds_it_and_a_fresh_name_finds_nothing() -> None:
    """PLANTED CONTROL: the same scan over a fresh name, a conventional name, a test or a non-Python file says no."""
    assert prior_art('src/pkg/beta/assembly.py', _TRACKED, _SRC) == ('src/pkg/alpha/assembly.py',)
    assert prior_art('src/pkg/beta/quadrature.py', _TRACKED, _SRC) == ()
    assert prior_art('src/pkg/beta/__init__.py', _TRACKED, _SRC) == ()
    assert prior_art('tests/test_x2.py', _TRACKED, _SRC) == ()
    assert prior_art('src/pkg/beta/assembly.md', _TRACKED, _SRC) == ()


def test_prior_art_is_cited_by_its_path_or_its_dotted_name() -> None:
    found = ('src/pkg/alpha/assembly.py',)
    assert uncited(found, '"""Assembly for beta."""', _SRC) == found
    assert uncited(found, '"""Sibling of src/pkg/alpha/assembly.py: beta differs in ..."""', _SRC) == ()
    assert uncited(found, '"""Sibling of pkg.alpha.assembly, for beta."""', _SRC) == ()


def _repo(tmp_path: Path) -> Path:
    run_git(tmp_path, 'init', '-q')
    module = tmp_path / 'src' / 'pkg' / 'alpha' / 'assembly.py'
    module.parent.mkdir(parents=True)
    module.write_text('"""Alpha assembly."""\n', encoding='utf-8')
    run_git(tmp_path, 'add', '.')
    return module


def test_the_write_refuses_an_uncited_duplicate_and_admits_a_cited_one_an_edit_or_a_fresh_name(tmp_path: Path) -> None:
    existing = _repo(tmp_path)
    new = tmp_path / 'src' / 'pkg' / 'beta' / 'assembly.py'
    refused = refuse_new_module(new, '"""Beta assembly."""\n', _SRC)
    assert refused is not None
    assert refused.startswith('PRIOR-ART-FIRST: src/pkg/beta/assembly.py')
    assert 'src/pkg/alpha/assembly.py' in refused
    assert refuse_new_module(new, '"""Unlike pkg.alpha.assembly, beta ..."""\n', _SRC) is None
    assert refuse_new_module(existing, '', _SRC) is None, 'an edit of an existing module is never new code'
    assert refuse_new_module(tmp_path / 'src' / 'pkg' / 'beta' / 'quadrature.py', '', _SRC) is None


def test_the_write_hook_denies_the_uncited_duplicate(tmp_path: Path, capsys, monkeypatch) -> None:
    # tmp_path lies under the OS temp dir, which WRITES-STAY-IN-THE-TREE refuses first; this test is about prior art.
    monkeypatch.setattr(codeplace, 'refuse_outside_tree', lambda _path: None)
    _repo(tmp_path)
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.placement]\ncode_roots = []\n', encoding='utf-8')
    new = str(tmp_path / 'src' / 'pkg' / 'beta' / 'assembly.py')
    payload = {'tool_name': 'Write', 'tool_input': {'file_path': new, 'content': '"""Beta."""\n'}}
    assert main(stdin=io.StringIO(json.dumps(payload))) == 0
    decision = json.loads(capsys.readouterr().out)['hookSpecificOutput']
    assert decision.get('permissionDecision') == 'deny', decision
    assert 'PRIOR-ART-FIRST' in decision['permissionDecisionReason']
    payload['tool_input']['content'] = '"""Beta; its alpha sibling is pkg.alpha.assembly."""\n'
    assert main(stdin=io.StringIO(json.dumps(payload))) == 0
    out = capsys.readouterr().out
    assert 'PRIOR-ART-FIRST' not in out, 'PLANTED CONTROL: the cited sibling is written'
