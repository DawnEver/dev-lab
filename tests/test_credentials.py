"""``lab_commons.credentials`` -- the git credential store, driven through a REAL git and planted helpers.

Every case plants its own ``credential.helper`` in a throwaway global config, so the box's real store is
never read or written, and every secret here is a fake the helper itself echoes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from lab_commons.credentials import (
    API_KEY_TASKS,
    NoCredential,
    api_key,
    credential_for,
    store_credential,
    task_username,
)
from lab_commons.dev import forge

#: What each platform's git or credential helper needs from the host: the loader path a module-built
#: git starts with (Ada), and the profile directories Git Credential Manager keeps its store under.
_HOST_VARS = ('LD_LIBRARY_PATH', 'HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA')


def _helper_config(tmp_path: Path, helper: str) -> dict[str, str]:
    config = tmp_path / 'gitconfig'
    config.write_text(f'[credential]\n\thelper = "{helper}"\n', encoding='utf-8')
    return {'GIT_CONFIG_GLOBAL': str(config), 'GIT_CONFIG_SYSTEM': str(tmp_path / 'absent')}


def test_a_given_env_keeps_what_git_and_its_helper_need_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A given env decides git's CONFIGURATION; it overlays the host's environment, never replaces it.

    Measured 2026-10-12, twice: on Ada a replaced env lost ``LD_LIBRARY_PATH`` and git exited 127; on
    Windows a blanked ``PATH`` hid ``git-credential-manager`` and ``forge queue`` reported a stored
    credential as missing. Every variable is planted, so each platform's need is asserted on every box.

    A plant is a real directory, and the loader path is EXTENDED, not replaced: a junk value would
    break the very git under test on a host whose git needs its ``LD_LIBRARY_PATH`` (Ada, 2026-10-12).
    """
    for name in _HOST_VARS:
        planted = tmp_path / f'planted-{name}'
        planted.mkdir()
        kept = os.environ.get(name) if name == 'LD_LIBRARY_PATH' else None
        monkeypatch.setenv(name, os.pathsep.join(filter(None, (kept, str(planted)))))
    echoed = '/'.join(f'${{{name}}}' for name in _HOST_VARS)
    env = _helper_config(tmp_path, f'!f() {{ echo username=u; echo password={echoed}; }}; f')
    seen = credential_for('forge.example.org', cwd=tmp_path, env=env)[1].split('/')
    # CONTAINED, not equal: Git for Windows' shell rewrites HOME into a POSIX path around the value.
    assert [name for name in _HOST_VARS if not any(f'planted-{name}' in part for part in seen)] == []


def test_a_helper_found_only_on_path_answers_through_a_given_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Git Credential Manager shape: ``helper = <name>`` resolved as ``git-credential-<name>`` on PATH."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    script = bin_dir / 'git-credential-planted'
    script.write_text('#!/bin/sh\necho username=u\necho password=from-path\n', encoding='utf-8', newline='\n')
    script.chmod(0o755)
    monkeypatch.setenv('PATH', f'{bin_dir}{os.pathsep}{os.environ["PATH"]}')
    env = {**os.environ, **_helper_config(tmp_path, 'planted')}
    assert credential_for('forge.example.org', cwd=tmp_path, env=env) == ('u', 'from-path')


def test_a_helper_that_cannot_be_started_is_named_not_reported_as_an_empty_store(tmp_path: Path) -> None:
    env = _helper_config(tmp_path, 'absent-helper-0b1d')
    with pytest.raises(NoCredential, match='could not be started') as caught:
        credential_for('forge.example.org', cwd=tmp_path, env=env)
    assert 'no stored credential' not in str(caught.value)


def test_no_stored_credential_refuses_and_never_answers_the_empty_string(tmp_path: Path) -> None:
    """An empty secret is a secret as far as a header is concerned; it would be sent and refused."""
    env = _helper_config(tmp_path, '!f() { :; }; f')
    with pytest.raises(NoCredential, match=r'forge\.example\.org'):
        credential_for('forge.example.org', cwd=tmp_path, env=env)


def test_fill_never_prompts_even_when_the_caller_asked_for_prompts(tmp_path: Path) -> None:
    """A host with nothing stored must refuse, not hang on a terminal or a GCM window nobody watches.

    The helper echoes the two switches it was started with; the caller's env tries to turn both back on.
    """
    env = {
        **_helper_config(tmp_path, '!f() { echo username=u; echo password=$GIT_TERMINAL_PROMPT/$GCM_INTERACTIVE; }; f'),
        'GIT_TERMINAL_PROMPT': '1',
        'GCM_INTERACTIVE': 'always',
    }
    assert credential_for('api.example.org', cwd=tmp_path, env=env)[1] == '0/never'


@pytest.mark.parametrize('variable', ['GIT_ASKPASS', 'SSH_ASKPASS'])
def test_an_askpass_program_is_never_asked_either(tmp_path: Path, variable: str) -> None:
    """``GIT_TERMINAL_PROMPT=0`` does not stop git's ASKPASS chain.

    Measured 2026-10-13: under VS Code, ``GIT_ASKPASS`` answered ``github.com`` from the editor's own login
    while the store was empty -- a prompt, and one that may block on a dialog. Planted here: an askpass
    that would answer, an empty store, and the refusal must still come.
    """
    askpass = tmp_path / 'askpass.sh'
    askpass.write_text('#!/bin/sh\necho planted-answer\n', encoding='utf-8', newline='\n')
    askpass.chmod(0o755)
    env = {**_helper_config(tmp_path, '!f() { :; }; f'), variable: askpass.as_posix(), 'DISPLAY': ':0'}
    with pytest.raises(NoCredential):
        credential_for('api.example.org', cwd=tmp_path, env=env)


def test_a_runtime_caller_needs_no_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``cwd`` is optional: a library caller asking for an API key has no checkout to stand in."""
    for name, value in _helper_config(tmp_path, '!f() { echo username=api-key; echo password=fake; }; f').items():
        monkeypatch.setenv(name, value)
    assert credential_for('api.example.org') == ('api-key', 'fake')


def test_store_hands_the_secret_to_the_helper_on_stdin_and_reads_it_back(tmp_path: Path) -> None:
    """Round trip through git's own ``store`` helper in a throwaway file: what is approved is what fill returns."""
    store = tmp_path / 'credentials'
    env = _helper_config(tmp_path, f'store --file={store.as_posix()}')
    store_credential('api.example.org', 'api-key', 'fake-secret', env=env)
    assert credential_for('api.example.org', env=env) == ('api-key', 'fake-secret')
    assert 'api.example.org' in store.read_text(encoding='utf-8')


def test_the_runtime_module_does_not_import_the_dev_kit() -> None:
    """A consumer without the ``dev`` extra reads its keys through this module, so it may not need ``dev``."""
    probe = (
        'import sys, lab_commons.credentials; print(sorted(m for m in sys.modules if m.startswith("lab_commons.dev")))'
    )
    done = subprocess.run(
        [sys.executable, '-c', probe], capture_output=True, text=True, encoding='utf-8', timeout=60, check=True
    )
    assert done.stdout.strip() == '[]'


def test_the_forge_reads_the_same_store() -> None:
    assert forge.credential_for is credential_for
    assert forge.NoCredential is NoCredential


def _store_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: dict[str, str]) -> None:
    """A planted helper holding *held* (username -> secret): it answers the username git asks for, else nothing."""
    cases = ' '.join(
        f'username={user}) echo username={user}; echo password={secret};;' for user, secret in held.items()
    )
    helper = f'!f() {{ while read -r line; do case "$line" in {cases} esac; done; }}; f'
    for name, value in _helper_config(tmp_path, helper).items():
        monkeypatch.setenv(name, value)


def test_a_task_key_is_its_own_username_under_the_providers_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store_of(tmp_path, monkeypatch, {'api-key': 'default', 'api-key-pr-review': 'the-review-key'})
    assert api_key('api.example.org') == 'default'
    assert api_key('api.example.org', task='pr-review') == 'the-review-key'


def test_a_missing_task_key_is_refused_by_name_and_never_falls_back_to_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PLANTED control: the default key IS stored on the same host, and must not answer for the task."""
    _store_of(tmp_path, monkeypatch, {'api-key': 'default'})
    assert api_key('api.example.org') == 'default'
    with pytest.raises(NoCredential, match='api-key-pr-review'):
        api_key('api.example.org', task='pr-review')


def test_a_helper_answering_another_username_is_refused_not_taken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A helper that ignores the username it was asked for would hand the default key to a task."""
    for name, value in _helper_config(tmp_path, '!f() { echo username=api-key; echo password=default; }; f').items():
        monkeypatch.setenv(name, value)
    with pytest.raises(NoCredential, match='api-key-optimization'):
        api_key('api.example.org', task='optimization')


def test_an_undeclared_task_is_refused_naming_the_declared_ones() -> None:
    with pytest.raises(ValueError, match='pr-review'):
        task_username('pr_reveiw')
    assert {task_username(task) for task in API_KEY_TASKS} == {f'api-key-{task}' for task in API_KEY_TASKS}
    assert task_username(None) == 'api-key'
    assert not any(task.isdigit() for task in API_KEY_TASKS)  # api-key-<N> is a fallback slot (ai_lab)
