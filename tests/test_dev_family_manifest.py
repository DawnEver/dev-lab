"""A repo with no pyproject.toml (a data repo) takes its branch declaration from the family's ``[family_repos]`` row.

PLANTED CONTROLS: a repo whose origin no family row names is still refused, naming BOTH doors (its manifest, or a
family row); a repo with its own manifest never reads the family.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _forge_fake import run_git
from lab_commons.config import config_path
from lab_commons.home import HOME_ENV

from dev_lab.dev.branchset import declared_branchset
from dev_lab.dev.lanepolicy import IntegrationNotDeclared, load_policy

_REMOTE = 'https://forge.example/o/data.git'


def _repo(path: Path, remote: str) -> Path:
    path.mkdir(parents=True)
    run_git(path, 'init', '-q')
    run_git(path, 'remote', 'add', 'origin', remote)
    return path


@pytest.fixture
def family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOME_ENV, str(tmp_path / 'home'))
    config_path().parent.mkdir(parents=True)
    config_path().write_text(
        f'[family_repos]\ndata = {{ remote = "{_REMOTE}", branch = "main" }}\n'
        'code = { remote = "https://forge.example/o/code.git", branch = "integrate/main" }\n',
        encoding='utf-8',
    )


@pytest.mark.usefixtures('family')
def test_a_data_repo_reads_its_integration_and_trunk_from_its_family_row(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'data', 'git@forge.example:o/data.git')
    assert load_policy(root).integration == 'main'
    declared = declared_branchset(root)
    assert declared.trunk == 'main'


@pytest.mark.usefixtures('family')
def test_a_repo_no_family_row_names_is_refused_naming_both_doors(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'stray', 'https://forge.example/o/stray.git')
    with pytest.raises(IntegrationNotDeclared) as refused:
        load_policy(root)
    assert 'pyproject.toml' in str(refused.value)
    assert '[family_repos]' in str(refused.value)


@pytest.mark.usefixtures('family')
def test_a_repo_with_its_own_manifest_never_reads_the_family(tmp_path: Path) -> None:
    root = _repo(tmp_path / 'code', 'https://forge.example/o/code.git')
    (root / 'pyproject.toml').write_text(
        '[tool.dev_lab.integrator]\nintegration = "dev"\n\n'
        '[tool.dev_lab.branchset]\ntrunk = "main"\nsessions = ["dev"]\n',
        encoding='utf-8',
    )
    assert load_policy(root).integration == 'dev'
