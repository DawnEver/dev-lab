"""SECURITY: the scans of :mod:`dev_lab.dev.security` can red, each on a planted control.

The planted controls run the real scanners over a throwaway git checkout, so a scanner that silently reads
nothing reds here. Judging a head and posting its status is :mod:`dev_lab.dev.forgesecurity`'s.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import run_git

from dev_lab.dev import security
from dev_lab.dev.security import (
    AdvisoriesUnreachable,
    ScanFailed,
    advisories,
    code_findings,
    locked_packages,
    scan_secrets,
    secret_findings,
    vulnerable,
)

_ROOT = Path(__file__).resolve().parent.parent

#: Assembled from halves so this file plants no hit in the tree scan below.
_TOKEN = 'ghp' + '_' + 'a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8'


def _checkout(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    run_git(root, 'init', '-q')
    run_git(root, 'add', '-A')
    return root


def test_a_planted_shell_true_reds(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {'src/pkg/run.py': 'import subprocess\n\nsubprocess.run(CMD, shell=True)\n'})
    found = code_findings(root, exclude={}, ignore={})
    assert [line.split(' ', 2)[1] for line in found] == ['S602'], found
    assert found[0].startswith('src/pkg/run.py:3:')


def test_the_family_default_waives_its_rules_and_trees_and_nothing_else(tmp_path: Path) -> None:
    root = _checkout(
        tmp_path,
        {
            'src/pkg/ok.py': 'import subprocess\n\n\ndef f(argv):\n    assert argv\n    subprocess.run(argv)\n',
            'tests/test_x.py': 'import subprocess\n\nsubprocess.run(CMD, shell=True)\n',
            'src/pkg/bad.py': 'import pickle\n\n\ndef f(b):\n    return pickle.loads(b)\n',
        },
    )
    found = code_findings(root, exclude={}, ignore={})
    assert [line.split(':')[0] for line in found] == ['src/pkg/bad.py'], found


def test_a_repo_difference_needs_a_reason(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {'attic/old.py': 'import pickle\n\npickle.loads(B)\n'})
    assert code_findings(root, exclude={'attic': 'read-only archive, never imported'}, ignore={}) == []
    with pytest.raises(ScanFailed, match='no reason'):
        code_findings(root, exclude={'attic': ' '}, ignore={})


def test_a_planted_secret_reds_by_digest_and_never_by_value(tmp_path: Path) -> None:
    root = _checkout(tmp_path, {'conf/settings.toml': f'token = "{_TOKEN}"\n', '.env': 'X=1\n', '.env.example': ''})
    found = secret_findings(root, allowed={})
    assert sorted(line.split(': ')[1] for line in found) == ['env file', 'github token'], found
    assert all(_TOKEN not in line for line in found)
    (digest,) = [line.rsplit(': ', 1)[-1] for line in found if ': github token: ' in line]
    assert secret_findings(root, allowed={digest: 'a test vector'}) == ['.env:0: env file: tracked']
    with pytest.raises(ScanFailed, match='no reason'):
        secret_findings(root, allowed={digest: ''})


@pytest.mark.parametrize(
    'planted',
    [
        '-----BEGIN RSA ' + 'PRIVATE KEY-----',
        'AKIA' + 'ABCDEFGHIJKLMNOP',
        'sk-ant-' + 'api03-abcdefghijklmnopqrstuv',
        'https://bot:' + 'hunter22@forge.example.org/x.git',
    ],
)
def test_each_credential_shape_is_found(planted: str) -> None:
    assert scan_secrets(planted), planted


@pytest.mark.parametrize(
    'clean',
    [
        'c9eaa7f1b3586128930be1c2608d514eb7a39e6a',
        'https://forge.example.org/owner/repo.git',
        'https://<user>:<token>@forge.example.org',
        'git@forge.example.org:owner/repo.git',
    ],
)
def test_a_neutral_value_is_not_a_credential(clean: str) -> None:
    assert scan_secrets(clean) == [], clean


def test_the_lock_audits_registry_pins_only(tmp_path: Path) -> None:
    lock = tmp_path / 'uv.lock'
    lock.write_text(
        'version = 1\n\n[[package]]\nname = "jinja2"\nversion = "2.4.1"\n'
        'source = { registry = "https://pypi.org/simple" }\n'
        '\n[[package]]\nname = "lab-commons"\nversion = "0.1"\nsource = { git = "https://forge.example.org/x" }\n',
        encoding='utf-8',
    )
    assert locked_packages(lock) == {'jinja2': '2.4.1'}


def test_an_advisory_reds_unless_accepted_with_a_reason() -> None:
    found = advisories({'jinja2': '2.4.1', 'idna': '3.10'}, query=lambda _: [{}, {'vulns': [{'id': 'GHSA-x'}]}])
    assert found == {'jinja2==2.4.1': ('GHSA-x',)}
    assert vulnerable(found, accepted={}) == ['jinja2==2.4.1: GHSA-x']
    assert vulnerable(found, accepted={'GHSA-x': 'not reachable: the template path is never used'}) == []
    with pytest.raises(ScanFailed, match='no reason'):
        vulnerable(found, accepted={'GHSA-x': ''})


def test_an_unreachable_database_is_inconclusive_and_never_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(security, '_OSV_HOST', 'osv.invalid')
    with pytest.raises(AdvisoriesUnreachable, match='INCONCLUSIVE'):
        advisories({'idna': '3.10'})
