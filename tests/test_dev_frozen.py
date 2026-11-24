"""USER-FROZEN-FILES: the three layers over one judgement, each with its planted controls.

Every layer is shown saying NO on a planted violation (a modified frozen file, a deleted one, an undeclared new
path, an agent write to the freeze file itself) and YES on the user's approved addition, so a green is a measurement.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev import codeplace, frozen
from dev_lab.dev._deny_frozen_row import USER_FROZEN_FILES
from dev_lab.dev.famtests import alwayson

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='needs git')

_SETTINGS = '.vscode/settings.json'
_BYTES = b'{"editor.rulers": [120]}\n'


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _freeze_text(tracked: list[str], frozen_rows: dict[str, str]) -> str:
    rows = '\n'.join(f'"{p}" = "{s}"' for p, s in {**frozen_rows, frozen.FREEZE_FILE: frozen.SELF}.items())
    listed = ', '.join(f'"{p}"' for p in sorted({*tracked, frozen.FREEZE_FILE}))
    return f'tracked = [{listed}]\n\n[frozen]\n{rows}\n'


def _git(root: Path, *args: str) -> None:
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)  # noqa: S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo opting in, freezing .vscode/settings.json at :data:`_BYTES`, everything staged and committed."""
    _git(tmp_path, 'init', '-q')
    (tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n\n[tool.dev_lab.freeze]\n', encoding='utf-8')
    (tmp_path / '.vscode').mkdir()
    (tmp_path / _SETTINGS).write_bytes(_BYTES)
    text = _freeze_text(['pyproject.toml', _SETTINGS], {_SETTINGS: _sha(_BYTES)})
    (tmp_path / frozen.FREEZE_FILE).write_text(text, encoding='utf-8')
    _git(tmp_path, 'add', '.')
    return tmp_path


def _commit_refusal(root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.chdir(root)
    out = io.BytesIO()
    code = frozen.main(['commit'], stdout=out)
    said = out.getvalue().decode('utf-8')
    assert (code == 1) == bool(said)
    return said


# ---- the judgement --------------------------------------------------------------------------------------------------


def test_parse_refuses_a_freeze_file_that_does_not_freeze_itself() -> None:
    with pytest.raises(ValueError, match='must freeze itself'):
        frozen.parse(f'tracked = ["{frozen.FREEZE_FILE}"]\n[frozen]\n')


def test_parse_refuses_a_frozen_row_without_a_sha256() -> None:
    with pytest.raises(ValueError, match='sha256'):
        frozen.parse(_freeze_text([_SETTINGS], {_SETTINGS: 'abc'}))


# ---- layer 2: the pre-commit row, on the INDEX ----------------------------------------------------------------------


def test_commit_admits_the_declared_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _commit_refusal(repo, monkeypatch) == ''


def test_commit_refuses_a_modified_frozen_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / _SETTINGS).write_bytes(b'{}\n')
    _git(repo, 'add', _SETTINGS)
    said = _commit_refusal(repo, monkeypatch)
    assert f'{_SETTINGS} is frozen and its bytes changed' in said
    assert 'Only the USER can unfreeze or approve' in said


def test_commit_refuses_a_deleted_frozen_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(repo, 'rm', '-q', '-f', _SETTINGS)
    assert f'{_SETTINGS} is frozen and was deleted' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_new_undeclared_path(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / 'new.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', 'new.py')
    assert 'new.py is tracked but not in the approved inventory' in _commit_refusal(repo, monkeypatch)


def test_commit_admits_an_addition_the_user_approved(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = _freeze_text(['pyproject.toml', _SETTINGS, 'new.py'], {_SETTINGS: _sha(_BYTES)})
    (repo / frozen.FREEZE_FILE).write_text(text, encoding='utf-8')
    (repo / 'new.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', '.')
    assert _commit_refusal(repo, monkeypatch) == ''


def test_commit_judges_the_staged_bytes_not_the_working_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / _SETTINGS).write_bytes(b'{}\n')  # unstaged: the commit would not carry it
    assert _commit_refusal(repo, monkeypatch) == ''


def test_a_repo_that_does_not_declare_is_never_judged(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    (repo / 'new.py').write_text('x = 1\n', encoding='utf-8')
    _git(repo, 'add', '.')
    assert _commit_refusal(repo, monkeypatch) == ''


# ---- layer 3: the always-on family check, on the checked-out tree ---------------------------------------------------


def test_family_check_reds_on_each_planted_violation(repo: Path) -> None:
    frozen.check(repo)  # the control: the declared tree passes
    (repo / _SETTINGS).write_bytes(b'{}\n')
    (repo / 'stray.txt').write_text('x', encoding='utf-8')
    _git(repo, 'add', '.')
    with pytest.raises(AssertionError) as caught:
        frozen.check(repo)
    assert 'its bytes changed' in str(caught.value)
    assert 'stray.txt is tracked but not in the approved inventory' in str(caught.value)


def test_family_check_is_wired_where_the_repo_declares(repo: Path) -> None:
    assert alwayson._applicable(repo).get(frozen.RULE_ID) is frozen.check
    (repo / 'pyproject.toml').write_text('[project]\nname = "x"\n\n[tool.dev_lab]\n', encoding='utf-8')
    assert frozen.RULE_ID not in alwayson._applicable(repo)  # the control: a member that does not declare


# ---- layer 1: the agent hooks ---------------------------------------------------------------------------------------


def test_write_hook_refuses_a_frozen_path_and_the_freeze_file_itself(repo: Path) -> None:
    assert frozen.RULE_ID in (frozen.refuse_write(repo / _SETTINGS) or '')
    assert frozen.RULE_ID in (frozen.refuse_write(repo / frozen.FREEZE_FILE) or '')
    assert frozen.refuse_write(repo / 'pyproject.toml') is None


def test_codeplace_hook_denies_an_edit_of_a_frozen_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    emitted: list[str] = []
    monkeypatch.setattr(codeplace, 'emit', emitted.append)
    monkeypatch.setattr(codeplace, 'refuse_outside_tree', lambda _path: None)  # the temp repo is outside every tree
    payload = {'tool_name': 'Edit', 'tool_input': {'file_path': str(repo / _SETTINGS)}, 'cwd': str(repo)}
    codeplace.main([], stdin=io.StringIO(json.dumps(payload)))
    assert any('"deny"' in line and frozen.RULE_ID in line for line in emitted)


@pytest.mark.parametrize(
    ('command', 'refused'),
    [
        (f'echo x > {_SETTINGS}', True),
        (f'echo x >> {_SETTINGS}', True),
        (f'rm {frozen.FREEZE_FILE}', True),
        (f'git rm {_SETTINGS}', True),
        (f'sed -i "s/a/b/" {_SETTINGS}', True),
        (f'cp other.json {_SETTINGS}', True),
        (f'Set-Content -Path {_SETTINGS} -Value x', True),
        (f'cat {_SETTINGS} > copy.json', False),
        (f'cp {_SETTINGS} copy.json', False),
        (f'cat {_SETTINGS} 2>&1', False),
        ('echo x > pyproject.toml', False),
    ],
)
def test_shell_judge_refuses_writes_onto_frozen_paths(repo: Path, command: str, *, refused: bool) -> None:
    payload = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': str(repo)}
    out = io.BytesIO()
    code = frozen.main(['--admit'], stdin=io.BytesIO(json.dumps(payload).encode()), stdout=out)
    assert (code == 1) is refused, out.getvalue()


def test_deny_row_asks_the_judge() -> None:
    assert USER_FROZEN_FILES['asks'] == 'dev_lab.dev.frozen'
    assert USER_FROZEN_FILES['id'] == frozen.RULE_ID
