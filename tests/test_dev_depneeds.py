"""On-demand extras (D78): a part's needs map to declared extras; a missing one is refused with its door."""

from __future__ import annotations

from pathlib import Path

import pytest

from dev_lab.dev import depneeds

_MANIFEST = (
    '[project]\nname="example"\nversion="0"\n'
    '[project.optional-dependencies]\n'
    'dev=["pytest"]\nsimba=["aesim.simba"]\nlearn=["learn-lab[torch]", "torch>=2.7"]\n'
    'gui=["PySide6>=6.7; sys_platform != \'linux\'"]\n'
    '[tool.dev_lab.dep]\nextras=["dev"]\nneeds={simba="simba", gpu="learn", desk="gui"}\n'
)


def _root(tmp_path: Path, text: str = _MANIFEST) -> Path:
    (tmp_path / 'pyproject.toml').write_text(text, encoding='utf-8')
    return tmp_path


def test_a_part_whose_need_maps_to_an_uninstalled_extra_names_the_sync_door(tmp_path: Path) -> None:
    root = _root(tmp_path)
    refusal = depneeds.missing_for_part(root, 'simba+windows', installed=lambda name: name == 'pytest')
    assert refusal is not None
    assert "needs extra 'simba'" in refusal
    # the door keeps the declared selection and adds the missing extra (explicit flags narrow)
    assert f'python -m dev_lab.dev.dep --sync {root} --extra dev --extra simba' in refusal


def test_an_installed_extra_admits_the_part(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same part with its extra present is admitted."""
    root = _root(tmp_path)
    assert depneeds.missing_for_part(root, 'simba', installed=lambda _name: True) is None


def test_requirement_names_drop_extras_versions_and_urls(tmp_path: Path) -> None:
    root = _root(tmp_path)
    seen: list[str] = []
    depneeds.missing_for_part(root, 'gpu', installed=lambda name: seen.append(name) or True)
    assert seen == ['learn-lab', 'torch']


def test_a_requirement_with_a_marker_is_not_judged(tmp_path: Path) -> None:
    """A marker this door cannot evaluate never makes an extra look missing."""
    root = _root(tmp_path)
    assert depneeds.missing_for_part(root, 'desk', installed=lambda _name: False) is None


def test_unmapped_needs_and_the_base_part_ask_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert depneeds.missing_for_part(root, 'base', installed=lambda _name: False) is None
    assert depneeds.missing_for_part(root, 'femm+windows', installed=lambda _name: False) is None
    assert depneeds.missing_for_part(root, '', installed=lambda _name: False) is None


def test_a_need_mapped_to_an_undeclared_extra_is_refused_by_name(tmp_path: Path) -> None:
    root = _root(tmp_path, _MANIFEST.replace('simba="simba"', 'simba="nosuch"'))
    with pytest.raises(ValueError, match=r"tool.dev_lab.dep.needs: simba -> 'nosuch' is no declared extra"):
        depneeds.missing_for_part(root, 'simba', installed=lambda _name: True)


def test_a_root_with_no_manifest_needs_nothing(tmp_path: Path) -> None:
    """A tree with no pyproject declares no needs, so no part is refused for a missing extra."""
    assert depneeds.declared_needs(tmp_path) == {}
    assert depneeds.missing_for_part(tmp_path, 'base') is None
