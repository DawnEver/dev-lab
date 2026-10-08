"""Family membership is the repo's own declaration, never a list of names kept here."""

from pathlib import Path

from lab_commons.dev.family import is_member


def _repo(tmp_path: Path, text: str | None) -> Path:
    if text is not None:
        (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


def test_a_repo_declaring_a_lab_commons_table_is_a_member(tmp_path: Path) -> None:
    assert is_member(_repo(tmp_path, "[tool.lab_commons.branchset]\ntrunk = 'main'\nsessions = []\n"))


def test_a_repo_without_the_table_is_not_a_member(tmp_path: Path) -> None:
    assert not is_member(_repo(tmp_path, "[project]\nname = 'stranger'\n"))


def test_no_manifest_or_an_unreadable_one_is_not_a_member(tmp_path: Path) -> None:
    assert not is_member(_repo(tmp_path, None))
    broken = tmp_path / 'broken'
    broken.mkdir()
    assert not is_member(_repo(broken, 'not = [toml'))


def test_this_checkout_is_a_member() -> None:
    assert is_member(Path(__file__).resolve().parents[1])
