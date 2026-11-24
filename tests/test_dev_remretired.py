"""REM-RETIRED: a repo's rem leftovers are refused and migrated once; a machine's rem install is removed by its door."""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import TYPE_CHECKING

import pytest

from dev_lab.dev import remretired

if TYPE_CHECKING:
    from pathlib import Path

_GIT = shutil.which('git') or 'git'


def _repo(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding='utf-8')
    subprocess.run([_GIT, 'init', '-q'], cwd=root, check=True, timeout=60)
    subprocess.run([_GIT, 'add', '-A'], cwd=root, check=True, timeout=60)
    return root


_LEFT = {
    '.claude/rules/rem/evidence.md': '# Evidence\n',
    '.claude/rules/invariant.md': '# Invariants\n',
    '.claude/rem.json': '{}\n',
    '.claude/memory-index.md': 'index\n',
    '.claude/.rem-state.json': '{}\n',
    'sub/.claude/memory/2026/11/01/x.md': '---\nname: x\ndescription: d\n---\n',
    'sub/.claude/memory-index.md': 'scoped index\n',
}


def test_every_leftover_is_found_and_refused_by_name(tmp_path: Path) -> None:
    root = _repo(tmp_path, _LEFT)
    assert remretired.leftovers(root) == [
        '.claude/.rem-state.json',
        '.claude/memory-index.md',
        '.claude/rem.json',
        '.claude/rules/rem',
        'sub/.claude/memory-index.md',
    ]
    with pytest.raises(AssertionError, match='REM-RETIRED') as refused:
        remretired.check(root)
    assert remretired.MIGRATE_DOOR in str(refused.value)


def test_a_clean_repo_passes(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same tree without the leftovers is silent -- memory and topic pages are not leftovers."""
    keep = {k: v for k, v in _LEFT.items() if 'memory/' in k or k == '.claude/rules/invariant.md'}
    remretired.check(_repo(tmp_path, keep))


def test_migrate_reports_then_applies_once_and_keeps_memory(tmp_path: Path) -> None:
    root = _repo(tmp_path, _LEFT)
    done, refused = remretired.migrate(root, apply=False)
    assert refused == []
    assert '.claude/rules/rem/evidence.md: would move to .claude/rules/evidence.md' in done
    assert (root / '.claude/rem.json').exists(), 'a dry run writes nothing'
    done, refused = remretired.migrate(root, apply=True)
    assert (root / '.claude/rules/evidence.md').read_text(encoding='utf-8') == '# Evidence\n'
    assert remretired.leftovers(root) == []
    assert (root / 'sub/.claude/memory/2026/11/01/x.md').exists()
    assert remretired.migrate(root, apply=True) == ([], []), 'a second run has nothing to do'


def test_a_page_whose_topic_page_exists_is_refused_for_a_hand_fold(tmp_path: Path) -> None:
    root = _repo(tmp_path, {'.claude/rules/rem/invariant.md': 'rem side\n', '.claude/rules/invariant.md': 'mine\n'})
    done, refused = remretired.migrate(root, apply=True)
    assert refused == ['.claude/rules/rem/invariant.md: its topic page invariant.md exists -- fold it by hand']
    assert (root / '.claude/rules/invariant.md').read_text(encoding='utf-8') == 'mine\n'
    assert remretired.leftovers(root) == ['.claude/rules/rem'], 'the unfolded page still refuses'
    assert done == []


def _machine(tmp_path: Path) -> tuple[Path, Path]:
    claude, codex = tmp_path / 'claude', tmp_path / 'codex'
    plugins = claude / 'plugins'
    (plugins / 'cache/cc-market/rem/3.1.0').mkdir(parents=True)
    (plugins / 'cache/cc-market/fabric/1.0.0').mkdir(parents=True)
    (plugins / 'data/rem-cc-market').mkdir(parents=True)
    registry = {'version': 2, 'plugins': {'rem@cc-market': [{}], 'fabric@cc-market': [{}]}}
    (plugins / 'installed_plugins.json').write_text(json.dumps(registry), encoding='utf-8')
    settings = {
        'enabledPlugins': {'rem@cc-market': True, 'fabric@cc-market': True},
        'env': {'LAB_COMMONS_HOME': '~/.m', 'REM_FORGE': '[]', 'OTHER': '1'},
    }
    (claude / 'settings.json').write_text(json.dumps(settings), encoding='utf-8')
    (codex / 'plugins/cache/cc-market/rem').mkdir(parents=True)
    (codex / 'config.toml').write_text(
        'model = "x"\n\n[plugins."rem@cc-market"]\nenabled = true\n\n'
        '[hooks.state."rem@cc-market:hooks/hooks.json:session_start:0:0"]\ntrusted = true\n\n'
        '[plugins."fabric@cc-market"]\nenabled = true\n',
        encoding='utf-8',
    )
    return claude, codex


def test_uninstall_names_then_removes_only_rem(tmp_path: Path) -> None:
    claude, codex = _machine(tmp_path)
    found = remretired.uninstall(claude, codex, apply=False)
    assert len(found) == 8, found
    assert (claude / 'plugins/cache/cc-market/rem').is_dir(), 'without --apply nothing is removed'
    remretired.uninstall(claude, codex, apply=True)
    assert remretired.installed(claude, codex) == []
    registry = json.loads((claude / 'plugins/installed_plugins.json').read_text(encoding='utf-8'))
    assert registry == {'version': 2, 'plugins': {'fabric@cc-market': [{}]}}
    settings = json.loads((claude / 'settings.json').read_text(encoding='utf-8'))
    assert settings == {'enabledPlugins': {'fabric@cc-market': True}, 'env': {'OTHER': '1'}}
    assert (claude / 'plugins/cache/cc-market/fabric/1.0.0').is_dir(), 'planted control: a neighbour plugin stays'
    config = (codex / 'config.toml').read_text(encoding='utf-8')
    assert 'rem@' not in config
    assert '[plugins."fabric@cc-market"]\nenabled = true\n' in config
    assert config.startswith('model = "x"\n')


def test_a_machine_without_rem_has_nothing_to_remove(tmp_path: Path) -> None:
    assert remretired.uninstall(tmp_path / 'c', tmp_path / 'x', apply=True) == []


def test_the_cli_exits_by_what_stays(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = _repo(tmp_path, _LEFT)
    assert remretired.main(['--root', str(root), 'check']) == 1
    assert 'REM-RETIRED' in capsys.readouterr().err
    assert remretired.main(['--root', str(root), 'migrate']) == 1, 'a dry run with work left is not done'
    assert remretired.main(['--root', str(root), 'migrate', '--apply']) == 0
    assert remretired.main(['--root', str(root), 'check']) == 0
