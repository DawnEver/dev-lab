"""USER-FROZEN-FILES: the three layers over one judgement, each with its planted controls.

Every layer is shown saying NO on a planted violation -- a frozen file modified or deleted (blob id moved), a file
changed inside a frozen directory (tree id moved), a missing, forged, foreign-digest or foreign-action receipt -- and
YES on the user's consented change, so a green is a measurement. The issuer is a test key: the check reads its public
half where it reads the declared one.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dev_lab.dev import codeplace, frozen
from dev_lab.dev._deny_frozen_row import USER_FROZEN_FILES
from dev_lab.dev.famtests import alwayson
from dev_lab.ops.consent.actions import ACTIONS
from dev_lab.ops.consent.credential import params_hash, sign

pytestmark = pytest.mark.skipif(shutil.which('git') is None, reason='needs git')

_SETTINGS = '.vscode/settings.json'
_DOCS = 'docs/guide'
_BYTES = b'{"editor.rulers": [120]}\n'
_REPO = 'acme-repo'
_ISSUER = Ed25519PrivateKey.generate()


def _credential(subject: str, *, key: Ed25519PrivateKey = _ISSUER, action: str = frozen.ACTION) -> bytes:
    """A credential as the issuer signs one (:func:`dev_lab.ops.consent.credential.sign`), issued a day ago."""
    issued = time.time() - 86400
    fields = {
        'id': str(uuid.uuid4()), 'action': action, 'subject': subject, 'params': {}, 'params_hash': params_hash({}),
        'scope': 'single', 'cap': None, 'plan': None, 'issued': issued, 'expires': issued + 900, 'issuer': 'test',
    }  # fmt: skip
    return json.dumps(sign(fields, key)).encode()


def _git(root: Path, *args: str) -> None:
    subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)  # noqa: S607


def _freeze(root: Path, **kwargs: object) -> None:
    """Freeze the settings file and the docs directory at their staged ids, with the user's receipt; stage it all."""
    _git(root, 'add', '.')
    rows = {path: frozen.index_object(root, path)[1] for path in (_SETTINGS, _DOCS)}  # type: ignore[index]
    lines = [f'"{path}" = "{oid}"' for path, oid in rows.items()]
    text = '[frozen]\n' + '\n'.join([*lines, f'"{frozen.FREEZE_FILE}" = "{frozen.SELF}"']) + '\n'
    (root / frozen.FREEZE_FILE).write_text(text, encoding='utf-8')
    want = frozen.subject(_REPO, (root / frozen.FREEZE_FILE).read_bytes())
    (root / frozen.RECEIPT_FILE).write_bytes(_credential(want, **kwargs))  # type: ignore[arg-type]
    _git(root, 'add', '.')


@pytest.fixture(autouse=True)
def issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The declared issuer key is the test issuer's public half."""
    monkeypatch.setattr(frozen, '_issuer_key', _ISSUER.public_key)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo opting in, freezing a file and a directory, with the user's receipt; everything staged."""
    _git(tmp_path, 'init', '-q')
    manifest = f'[project]\nname = "x"\n\n[tool.dev_lab.freeze]\nrepo = "{_REPO}"\n'
    (tmp_path / 'pyproject.toml').write_text(manifest, encoding='utf-8')
    (tmp_path / '.vscode').mkdir()
    (tmp_path / _SETTINGS).write_bytes(_BYTES)
    (tmp_path / _DOCS).mkdir(parents=True)
    (tmp_path / _DOCS / 'a.md').write_text('# A\n', encoding='utf-8')
    _freeze(tmp_path)
    return tmp_path


def _commit_refusal(root: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.chdir(root)
    out = io.BytesIO()
    code = frozen.main(['commit'], stdout=out)
    said = out.getvalue().decode('utf-8')
    assert (code == 1) == bool(said)
    return said


def _change_settings(root: Path) -> None:
    (root / _SETTINGS).write_bytes(b'{}\n')
    _git(root, 'add', _SETTINGS)


# ---- the judgement --------------------------------------------------------------------------------------------------


def test_parse_refuses_a_freeze_file_that_does_not_freeze_itself() -> None:
    with pytest.raises(ValueError, match='must freeze itself'):
        frozen.parse('[frozen]\n')


def test_parse_refuses_a_frozen_row_without_an_object_id() -> None:
    with pytest.raises(ValueError, match='git object id'):
        frozen.parse(f'[frozen]\n"a" = "abc"\n"{frozen.FREEZE_FILE}" = "self"\n')


def test_parse_refuses_a_retired_inventory() -> None:
    with pytest.raises(ValueError, match='only \\[frozen\\]'):
        frozen.parse(f'tracked = []\n[frozen]\n"{frozen.FREEZE_FILE}" = "self"\n')


def test_the_action_is_registered_where_consent_actions_are() -> None:
    row = ACTIONS[frozen.ACTION]
    assert (row.scope, row.params) == ('single', {})


# ---- layer 2: the pre-commit row, on the INDEX ----------------------------------------------------------------------


def test_commit_admits_the_consented_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _commit_refusal(repo, monkeypatch) == ''


def test_commit_refuses_a_modified_frozen_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _change_settings(repo)
    said = _commit_refusal(repo, monkeypatch)
    assert f'{_SETTINGS} is frozen and its blob changed' in said
    assert 'Only the USER approves' in said
    assert '-m dev_lab.dev.frozen request' in said  # the door


def test_commit_refuses_a_deleted_frozen_file(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git(repo, 'rm', '-q', '-f', _SETTINGS)
    assert f'{_SETTINGS} is frozen and was deleted' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_changed_file_inside_a_frozen_directory(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / _DOCS / 'a.md').write_text('# A, edited\n', encoding='utf-8')
    _git(repo, 'add', '.')
    assert f'{_DOCS} is frozen and its tree changed' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_new_file_inside_a_frozen_directory(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / _DOCS / 'b.md').write_text('# B\n', encoding='utf-8')
    _git(repo, 'add', '.')
    assert f'{_DOCS} is frozen and its tree changed' in _commit_refusal(repo, monkeypatch)


def test_commit_admits_a_change_the_user_consented_to(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _change_settings(repo)
    _freeze(repo)  # re-frozen at the new blob, with a receipt for the new freeze file
    assert _commit_refusal(repo, monkeypatch) == ''


def test_commit_refuses_a_redraft_without_a_receipt(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _change_settings(repo)
    _freeze(repo)
    _git(repo, 'rm', '-q', '--cached', frozen.RECEIPT_FILE)
    assert f'{frozen.RECEIPT_FILE} is missing' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_receipt_for_another_digest(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old = (repo / frozen.RECEIPT_FILE).read_bytes()
    _change_settings(repo)
    _freeze(repo)
    (repo / frozen.RECEIPT_FILE).write_bytes(old)  # the user approved the OLD freeze file
    _git(repo, 'add', '.')
    assert 'the user approved another freeze.toml' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_forged_receipt(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _change_settings(repo)
    _freeze(repo, key=Ed25519PrivateKey.generate())  # the agent's own key, not the issuer's
    assert 'does not verify' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_a_receipt_for_another_action(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _freeze(repo, action='desktop.open')
    assert 'approves desktop.open' in _commit_refusal(repo, monkeypatch)


def test_commit_refuses_when_no_issuer_key_is_declared(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(frozen, '_issuer_key', lambda: None)
    assert 'no consent issuer key is declared' in _commit_refusal(repo, monkeypatch)


def test_commit_judges_the_staged_bytes_not_the_working_tree(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / _SETTINGS).write_bytes(b'{}\n')  # unstaged: the commit would not carry it
    assert _commit_refusal(repo, monkeypatch) == ''


def test_a_repo_that_does_not_declare_is_never_judged(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    _change_settings(repo)
    _git(repo, 'add', '.')
    assert _commit_refusal(repo, monkeypatch) == ''


# ---- the door: request and receipt ----------------------------------------------------------------------------------


def test_request_writes_the_consent_request_for_the_draft(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    out = io.BytesIO()
    assert frozen.main(['request'], stdout=out) == 0
    written = next((repo / 'output').rglob('freeze-*.json'))
    request = json.loads(written.read_text(encoding='utf-8'))
    assert request == {
        'action': frozen.ACTION,
        'subject': frozen.subject(_REPO, (repo / frozen.FREEZE_FILE).read_bytes()),
        'params': {},
    }
    assert '-m dev_lab.ops.consent grant' in out.getvalue().decode()


def test_receipt_places_only_a_credential_for_the_draft(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo)
    stale = repo / 'stale.json'
    stale.write_bytes(_credential(frozen.subject(_REPO, b'another draft')))
    assert frozen.main(['receipt', str(stale)], stdout=io.BytesIO()) == 1  # the control: another approval
    good = repo / 'good.json'
    good.write_bytes(_credential(frozen.subject(_REPO, (repo / frozen.FREEZE_FILE).read_bytes())))
    assert frozen.main(['receipt', str(good)], stdout=io.BytesIO()) == 0
    assert (repo / frozen.RECEIPT_FILE).read_bytes() == good.read_bytes()


# ---- layer 3: the always-on family check ----------------------------------------------------------------------------


def test_family_check_reds_on_each_planted_violation(repo: Path) -> None:
    frozen.check(repo)  # the control: the consented tree passes
    _change_settings(repo)
    (repo / _DOCS / 'a.md').write_text('# A, edited\n', encoding='utf-8')
    _git(repo, 'add', '.')
    with pytest.raises(AssertionError) as caught:
        frozen.check(repo)
    assert 'its blob changed' in str(caught.value)
    assert 'its tree changed' in str(caught.value)


def test_family_check_reds_on_a_forged_receipt(repo: Path) -> None:
    _freeze(repo, key=Ed25519PrivateKey.generate())
    with pytest.raises(AssertionError, match='does not verify'):
        frozen.check(repo)


def test_family_check_is_wired_where_the_repo_declares(repo: Path) -> None:
    assert alwayson._applicable(repo).get(frozen.RULE_ID) is frozen.check
    (repo / 'pyproject.toml').write_text('[project]\nname = "x"\n\n[tool.dev_lab]\n', encoding='utf-8')
    assert frozen.RULE_ID not in alwayson._applicable(repo)  # the control: a member that does not declare


# ---- layer 1: the agent hooks ---------------------------------------------------------------------------------------


def test_write_hook_refuses_frozen_paths_but_admits_the_draft(repo: Path) -> None:
    assert frozen.RULE_ID in (frozen.refuse_write(repo / _SETTINGS) or '')
    assert 'inside frozen docs/guide' in (frozen.refuse_write(repo / _DOCS / 'new.md') or '')
    assert frozen.refuse_write(repo / frozen.FREEZE_FILE) is None  # the agent drafts; the receipt approves
    assert frozen.refuse_write(repo / 'docs' / 'guided.md') is None  # a sibling sharing the prefix is not inside
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
        (f'echo x > {_DOCS}/b.md', True),
        (f'rm {_SETTINGS}', True),
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
