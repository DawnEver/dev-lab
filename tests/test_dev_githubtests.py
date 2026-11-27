"""GITHUB-TESTS-ON-ACTIONS: no host produces a test part of a repo hosted on github.com (user ruling 2026-11-27)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Final

from dev_lab.dev.githubtests import account_refusals, family_refusals, on_github
from dev_lab.ops.configcheck import check_family, check_host

FAMILY: Final = """\
[hpc.clusters.c]
root = "/fs/{user}/lab"

[[hpc.grant]]
user = "v"
cluster = "c"
slurm_account = "free"
role = "verification"

[roles.github]
tests = "ci"
review = { host = "judge" }
merge = "ci"
promote = "ci"
prune = "ci"

[roles.gitea]
tests = { hpc = "c", role = "verification" }
review = { host = "judge" }
merge = { hpc = "c", role = "verification" }
promote = { host = "judge" }
prune = { hpc = "c", role = "verification" }

[family_repos]
learn-lab = { remote = "https://github.com/o/learn-lab.git", branch = "main" }
wdg = { remote = "https://gitea.example/t/wdg.git", branch = "main" }
"""
GITHUB_ROW: Final = '{ name = "learn-lab", url = "https://github.com/o/learn-lab.git", ref = "main" }'
GITEA_ROW: Final = '{ name = "wdg", url = "https://gitea.example/t/wdg.git", ref = "main" }'
#: Binds learn-lab's tests to the verification grant: the account would produce its parts.
ON_HPC: Final = '\n[roles.repos."o/learn-lab"]\ntests = { hpc = "c", role = "verification" }\n'


def _account(row: str) -> dict[str, Any]:
    return tomllib.loads(f'[deploy]\nhost = "login"\nrepos = [{row}]\n')


def test_the_forge_of_a_remote_is_read_from_its_host() -> None:
    assert on_github('https://github.com/o/learn-lab.git')
    assert not on_github('https://gitea.example/t/wdg.git')
    assert not on_github('not a remote')


def test_a_github_repo_bound_off_ci_is_refused_by_name_with_its_door() -> None:
    """PLANTED CONTROL: the family as shipped (GitHub on ci, Gitea on the cluster) passes."""
    assert family_refusals(tomllib.loads(FAMILY)) == []
    found = family_refusals(tomllib.loads(FAMILY + ON_HPC))
    assert len(found) == 1, found
    assert '[roles.repos."o/learn-lab"] tests' in found[0]
    assert 'GITHUB-TESTS-ON-ACTIONS' in found[0]
    assert 'its parts come from GitHub Actions: declare them in [tool.dev_lab.parts] hosted' in found[0]


def test_the_github_forge_table_bound_off_ci_is_refused_once() -> None:
    family = FAMILY.replace('[roles.github]\ntests = "ci"', '[roles.github]\ntests = { host = "judge" }')
    found = family_refusals(tomllib.loads(family))
    assert len(found) == 1, found
    assert found[0].startswith('[roles.github] tests = { host = "judge" }')


def test_a_verification_account_serving_a_github_repo_is_refused_and_a_gitea_one_passes() -> None:
    """PLANTED CONTROL: a gitea repo the family serves on this verification account passes; learn-lab is named."""
    layer = tomllib.loads(FAMILY + ON_HPC)
    assert account_refusals('c-v', _account(GITEA_ROW), layer) == []
    found = account_refusals('c-v', _account(GITHUB_ROW), layer)
    assert len(found) == 1, found
    assert 'learn-lab' in found[0]
    assert 'GITHUB-TESTS-ON-ACTIONS' in found[0]
    assert '[tool.dev_lab.parts] hosted' in found[0]


def test_a_github_row_serving_nothing_or_claiming_nothing_passes() -> None:
    """The kit's checkout of a GitHub repo is inert when no role binds it here, or when the row claims nothing."""
    assert account_refusals('c-v', _account(GITHUB_ROW), tomllib.loads(FAMILY)) == []
    claimed = GITHUB_ROW.replace(' }', ', claims = "none" }')
    assert account_refusals('c-v', _account(claimed), tomllib.loads(FAMILY + ON_HPC)) == []


def test_configcheck_runs_both_refusals(tmp_path: Path) -> None:
    family = tmp_path / 'family.toml'
    family.write_text(FAMILY + ON_HPC, encoding='utf-8')
    assert [line for line in check_family(family) if 'GITHUB-TESTS-ON-ACTIONS' in line]
    account = tmp_path / 'c-v.toml'
    account.write_text(f'[deploy]\nhost = "login"\npython = "3.13"\nrepos = [{GITHUB_ROW}]\n', encoding='utf-8')
    assert [line for line in check_host(account, family) if 'GITHUB-TESTS-ON-ACTIONS' in line and 'learn-lab' in line]
    account.write_text(f'[deploy]\nhost = "login"\npython = "3.13"\nrepos = [{GITEA_ROW}]\n', encoding='utf-8')
    assert not [line for line in check_host(account, family) if 'GITHUB-TESTS-ON-ACTIONS' in line]
