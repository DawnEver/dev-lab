"""Family membership is the repo's own declaration, never a list of names kept here."""

import tomllib
from pathlib import Path

from dev_lab.dev.family import declared_table, is_member


def _repo(tmp_path: Path, text: str | None) -> Path:
    if text is not None:
        (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


def test_a_repo_declaring_a_dev_lab_or_a_lab_commons_table_is_a_member(tmp_path: Path) -> None:
    assert is_member(_repo(tmp_path, "[tool.dev_lab.branchset]\ntrunk = 'main'\nsessions = []\n"))
    kit = tmp_path / 'kit'
    kit.mkdir()
    assert is_member(_repo(kit, "[tool.lab_commons.hpc]\ninstall = 'uv sync'\n"))


def test_a_repo_without_the_table_is_not_a_member(tmp_path: Path) -> None:
    assert not is_member(_repo(tmp_path, "[project]\nname = 'stranger'\n"))


def test_no_manifest_or_an_unreadable_one_is_not_a_member(tmp_path: Path) -> None:
    assert not is_member(_repo(tmp_path, None))
    broken = tmp_path / 'broken'
    broken.mkdir()
    assert not is_member(_repo(broken, 'not = [toml'))


def test_this_checkout_is_a_member() -> None:
    assert is_member(Path(__file__).resolve().parents[1])


def test_a_dev_lab_table_is_read_from_its_own_namespace_and_never_from_the_old_one() -> None:
    """PLANTED CONTROL: the same table under ``[tool.lab_commons]`` is invisible -- no fallback, no alias."""
    new = tomllib.loads("[tool.dev_lab.hooks]\npre-commit = ['x']\n")
    old = {'tool': {'lab_commons': {'hooks': {'pre-commit': ['x']}}}}
    assert declared_table(new, 'hooks') == {'pre-commit': ['x']}
    assert declared_table(old, 'hooks') is None
    assert declared_table(old, 'hooks', {}) == {}
