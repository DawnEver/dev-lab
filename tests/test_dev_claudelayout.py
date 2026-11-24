"""THE CLOSED `.claude/` INVENTORY (user ruling 2026-11-24): only at the root, every entry declared by name.

The one constant is :data:`dev_lab.dev.claudelayout.CLAUDE_ENTRIES`.

Each arm plants the case the check must refuse beside the case it must accept, so a check that can only say
yes reds here.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from dev_lab.dev.claudelayout import CLAUDE_ENTRIES, RETIRED_CLAUDE_ENTRIES, stray_entries
from dev_lab.dev.famtests.claudelayout import assert_claude_layout_is_closed

ROOT = Path(__file__).resolve().parents[1]

#: One path per declared entry: the honest tree every planted control starts from.
_HONEST = (
    'settings.json',
    'settings.local.json',
    'automode.json',
    'hooks/deny-commands.js',
    'hooks/venv_resolver.js',
    'hooks/py.js',
    'hooks/deny-rules.json',
    'hooks/native_session.json',
    'memory/2026/11/24/a-finding.md',
    'worktrees/some-lane/README.md',
)


def _tree(root: Path, rels: tuple[str, ...]) -> Path:
    subprocess.run([shutil.which('git') or 'git', 'init', '-q', str(root)], check=True, timeout=60)
    for rel in rels:
        path = root / '.claude' / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x\n', encoding='utf-8')
    return root


def test_the_inventory_is_one_constant_and_the_retired_names_carry_their_reason() -> None:
    """The list is data: the user's ruling, entry by entry, and no retired name is also allowed."""
    assert set(CLAUDE_ENTRIES) == {
        'settings.json',
        'settings.local.json',
        'automode.json',
        'hooks/deny-commands.js',
        'hooks/venv_resolver.js',
        'hooks/py.js',
        'hooks/deny-rules.json',
        'hooks/native_session.json',
        'memory/<yyyy>/<mm>/<dd>/*.md',
        'worktrees/<name>/',
    }
    assert all(why.strip() for why in (*CLAUDE_ENTRIES.values(), *RETIRED_CLAUDE_ENTRIES.values()))
    assert not set(CLAUDE_ENTRIES) & set(RETIRED_CLAUDE_ENTRIES)


def test_an_honest_tree_is_closed(tmp_path: Path) -> None:
    """Every declared entry present, nothing else: no complaint."""
    assert stray_entries(_tree(tmp_path, _HONEST)) == ()


@pytest.mark.parametrize(
    ('rel', 'needle'),
    [
        ('rem.json', 'RETIRED'),
        ('sharp-review.json', 'RETIRED'),
        ('tasks/x/JOURNAL.md', 'RETIRED'),
        ('rules/principles.md', 'RETIRED'),
        ('.rem-state.json', 'RETIRED'),
        ('memory-index.md', 'RETIRED'),
        ('agents/x.md', 'undeclared'),
        ('hooks/stray.js', 'undeclared'),
        ('memory/_meta.json', 'undeclared'),
        ('memory/2026/11/24/_meta.json', 'undeclared'),
        ('memory/2026/11/a.md', 'undeclared'),
        ('worktrees/stray-file', 'undeclared'),
    ],
)
def test_a_planted_entry_outside_the_inventory_is_refused_by_name(tmp_path: Path, rel: str, needle: str) -> None:
    """PLANTED CONTROL: the honest tree plus one stray entry reds, naming the entry and why."""
    found = stray_entries(_tree(tmp_path, (*_HONEST, rel)))
    assert len(found) == 1, found
    assert f'.claude/{rel}'.startswith(found[0].split(': ')[0]), found
    assert needle in found[0]


def test_a_nested_claude_directory_is_refused(tmp_path: Path) -> None:
    """`.claude/` exists only at the repo root: one under src/ reds, the root one alone does not."""
    root = _tree(tmp_path, _HONEST)
    nested = root / 'src' / 'pkg' / '.claude'
    nested.mkdir(parents=True)
    (nested / 'settings.json').write_text('{}\n', encoding='utf-8')
    found = stray_entries(root)
    assert found == ('src/pkg/.claude: a .claude/ below the repo root -- only the root one exists',), found


def test_the_body_raises_with_every_stray_named(tmp_path: Path) -> None:
    """The famtests body is what a consumer runs; it reds with the list, and passes the honest tree."""
    root = _tree(tmp_path, _HONEST)
    assert_claude_layout_is_closed(root=root)
    (root / '.claude' / 'rem.json').write_text('{}\n', encoding='utf-8')
    with pytest.raises(AssertionError, match=r'\.claude/rem\.json: RETIRED'):
        assert_claude_layout_is_closed(root=root)


@pytest.mark.xfail(
    strict=True,
    reason=(
        'RESIDUAL 2026-11-24: the kit tracks the month summaries .claude/memory/<yyyy>/<mm>/SUMMARY-*.md, '
        'which the ruled list does not declare -- awaiting the user`s call on the summaries'
    ),
)
def test_the_kit_holds_a_closed_claude_directory() -> None:
    """THE ADOPTION, run by the kit on the kit."""
    assert_claude_layout_is_closed(root=ROOT)
