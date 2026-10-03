"""PROJECT-FILES-HAVE-ONE-SOURCE: the family list, the one renderer, and both famtests bodies -- each planted.

The kit runs both bodies on itself (it is an adopter like any other), and every refusal is driven over
a throwaway repository in ``tmp_path`` so a green here is a measurement and not a reader of nothing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest
from _famconfig_delta import DELTAS, REPO

from lab_commons.dev.famconfig import BASES, RENDERED
from lab_commons.dev.famfiles import MANAGED, OWNED, PROJECT_FILES, main, project_files_on_disk, render_all
from lab_commons.dev.famtests.famfiles import (
    assert_every_managed_file_is_rendered,
    assert_every_project_file_is_accounted_for,
)

ROOT: Final = Path(__file__).resolve().parents[1]
DELTAS_FILE: Final = ROOT / 'tests' / '_famconfig_delta.py'
RERENDER: Final = 'python -m lab_commons.dev.famfiles --deltas tests/_famconfig_delta.py'


def _git(*args: str, cwd: Path) -> None:
    subprocess.run([shutil.which('git') or 'git', *args], cwd=cwd, check=True, capture_output=True, timeout=60)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository tracking three family files, rendered from the kit's own deltas."""
    root = tmp_path / 'repo'
    root.mkdir()
    _git('init', '-q', cwd=root)
    render_all(root, {name: DELTAS[name] for name in DELTAS if BASES[name].mode == RENDERED}, write=True)
    (root / 'pyproject.toml').write_text('[project]\nname = "x"\n', encoding='utf-8')
    _git('add', '.', cwd=root)
    return root


def test_every_family_base_is_a_managed_row_and_every_row_says_how() -> None:
    """BY CONSTRUCTION: a base added to famconfig cannot be missing from the one list."""
    assert {name for name in BASES if PROJECT_FILES.get(name, None) is None} == set()
    assert all(PROJECT_FILES[name].kind == MANAGED for name in BASES)
    assert {row.kind for row in PROJECT_FILES.values()} == {MANAGED, OWNED}
    assert all(row.how.strip() for row in PROJECT_FILES.values()), 'a row with no mechanism or reason'


def test_the_kit_accounts_for_every_project_file_it_tracks() -> None:
    """THE ADOPTION, run by the kit on the kit -- with nothing owned beyond the family list."""
    assert len(project_files_on_disk(ROOT)) >= 6
    assert_every_project_file_is_accounted_for(root=ROOT, owned_here={})


def test_the_kit_renders_every_managed_file() -> None:
    """Every base declared, none forked, every file base plus delta."""
    assert_every_managed_file_is_rendered(root=ROOT, deltas=DELTAS, repo=REPO, rerender_hint=RERENDER)


def test_the_one_command_reports_the_kit_current() -> None:
    """The CLI in check mode over this checkout: nothing would change."""
    assert main(['--repo', str(ROOT), '--deltas', str(DELTAS_FILE), '--check']) == 0


def test_a_planted_unlisted_file_is_refused_until_it_is_owned_with_a_reason(repo: Path) -> None:
    """PLANTED CONTROL for the list: a file nobody declared reds, and owning it with a reason greens."""
    assert_every_project_file_is_accounted_for(root=repo, owned_here={})
    (repo / 'tox.ini').write_text('[tox]\n', encoding='utf-8')
    _git('add', 'tox.ini', cwd=repo)
    with pytest.raises(AssertionError, match=r'tox\.ini: tracked, and neither'):
        assert_every_project_file_is_accounted_for(root=repo, owned_here={})
    assert_every_project_file_is_accounted_for(root=repo, owned_here={'tox.ini': 'this repo alone runs tox'})


@pytest.mark.parametrize(
    ('owned', 'needle'),
    [
        ({'.gitignore': 'mine'}, 'AND a family row'),
        ({'tox.ini': '  '}, 'no reason'),
        ({'tox.ini': 'gone'}, 'not tracked'),
    ],
)
def test_a_lying_owned_entry_is_refused(repo: Path, owned: dict[str, str], needle: str) -> None:
    """A restated family row, an empty reason and an entry outliving its file are each named."""
    with pytest.raises(AssertionError, match=needle):
        assert_every_project_file_is_accounted_for(root=repo, owned_here=owned)


def test_one_render_writes_every_rendered_artefact_and_a_hand_edit_reds(repo: Path) -> None:
    """The renderer and the check, round trip: rendered files are current; a hand edit is reported."""
    rendered = {name: DELTAS[name] for name in DELTAS if BASES[name].mode == RENDERED}
    lines = render_all(repo, rendered, write=False)
    assert [line for line in lines if line.split(':')[0] in rendered] == [
        f'{name}: current' for name in sorted(rendered)
    ]
    path = repo / '.gitignore'
    path.write_text(path.read_text(encoding='utf-8').replace('scratch/\n', ''), encoding='utf-8')
    assert any(line.startswith('.gitignore: would render') for line in render_all(repo, rendered, write=False))
    render_all(repo, rendered, write=True)
    assert 'scratch/\n' in path.read_text(encoding='utf-8')
