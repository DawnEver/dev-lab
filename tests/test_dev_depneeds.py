"""On-demand extras (D78): a part's needs map to declared extras; a missing one is refused with its door."""

from __future__ import annotations

from pathlib import Path

import pytest
from _task_ledger import on_branch, open_task, plant_ledger

from dev_lab.dev import depneeds

_MANIFEST = (
    '[project]\nname="example"\nversion="0"\n'
    '[project.optional-dependencies]\n'
    'dev=["pytest"]\nsimba=["aesim.simba"]\nlearn=["learn-lab[torch]", "torch>=2.7"]\n'
    'gui=["PySide6>=6.7; sys_platform != \'linux\'"]\n'
    '[tool.dev_lab.dep]\nextras=["dev"]\nneeds={simba="simba", gpu="learn", desk="gui"}\n'
)


def _root(tmp_path: Path, text: str = _MANIFEST) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
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
    with pytest.raises(ValueError, match=r"names \['nosuch'\], no declared extra"):
        depneeds.missing_for_part(root, 'simba', installed=lambda _name: True)


# --- D79: a task declares the needs its work exercises; dep maps them to extras through the repo's table ---


def _ledger(tmp_path: Path, frontmatter_needs: str | None) -> Path:
    task = tmp_path / 'ledger' / 'work'
    task.mkdir(parents=True)
    needs = '' if frontmatter_needs is None else f'needs: {frontmatter_needs}\n'
    (task / 'TASK.md').write_text(
        f'---\nname: work\nkind: task\nstatus: open\n{needs}---\n\n# work\n', encoding='utf-8'
    )
    return tmp_path / 'ledger'


def test_a_task_needing_simba_selects_its_extra_without_an_explicit_flag(tmp_path: Path) -> None:
    root = _root(tmp_path)
    ledger = _ledger(tmp_path, '[simba, windows]')
    needs = depneeds.task_needs(ledger, 'work@abc')
    assert needs == ('simba', 'windows')
    assert depneeds.extras_for(root, needs) == ('dev', 'simba')


def test_a_task_declaring_no_needs_keeps_the_declared_extras(tmp_path: Path) -> None:
    """PLANTED CONTROL: no needs line -- only what the repo declares, nothing more."""
    root = _root(tmp_path)
    assert depneeds.task_needs(_ledger(tmp_path, None), 'work@abc') == ()
    assert depneeds.extras_for(root, ()) == ('dev',)


def test_a_need_the_repo_maps_to_no_extra_adds_none(tmp_path: Path) -> None:
    """A need with no extra (a platform, an external tool) is a test marker only: it installs nothing."""
    root = _root(tmp_path)
    assert depneeds.extras_for(root, ('windows', 'femm')) == ('dev',)


def test_a_malformed_needs_line_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match='needs'):
        depneeds.task_needs(_ledger(tmp_path, 'simba windows'), 'work@abc')


def test_dep_selects_the_branchs_task_extras_and_none_off_a_task_branch(tmp_path: Path) -> None:
    """The dep door reads the task the checkout's branch names; on no task head it keeps the default (control)."""
    root = _root(tmp_path / 'work')
    open_task(plant_ledger(), 'work', extra='needs: [simba]\n')
    on_branch(root, 'main')
    assert depneeds.task_extras(root) is None
    on_branch(root, 'pr/work/x')
    assert depneeds.task_extras(root) == ('dev', 'simba')


def test_a_root_with_no_manifest_needs_nothing(tmp_path: Path) -> None:
    """A tree with no pyproject declares no needs, so no part is refused for a missing extra."""
    assert depneeds.declared_needs(tmp_path) == {}
    assert depneeds.missing_for_part(tmp_path, 'base') is None


# --- one reader: CI's per-part sync derives its extras through lab_commons.extras ---


def test_a_part_needing_nothing_heavy_syncs_only_the_declared_extras(tmp_path: Path) -> None:
    root = _root(tmp_path)
    assert depneeds.flags(root, 'base') == '--extra dev'
    assert depneeds.flags(root, 'gpu+simba') == '--extra dev --extra learn --extra simba'


def test_the_flags_door_prints_the_part_selection_and_refuses_an_undeclared_default(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    assert depneeds.main(['flags', '--root', str(root), '--part', 'simba']) == 0
    assert capsys.readouterr().out.strip() == '--extra dev --extra simba'
    undeclared = _root(tmp_path, _MANIFEST.replace('extras=["dev"]\n', ''))
    assert depneeds.main(['flags', '--root', str(undeclared)]) == 2, 'planted: no declared extras is refused'
