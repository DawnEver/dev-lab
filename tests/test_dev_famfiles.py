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

from dev_lab.dev.famconfig import BASES, RENDERED
from dev_lab.dev.famfiles import (
    MANAGED,
    OWNED,
    PROJECT_FILES,
    RENDERERS,
    due_renderers,
    main,
    project_files_on_disk,
    render_all,
    render_argv,
)
from dev_lab.dev.famtests.famfiles import (
    assert_every_managed_file_is_rendered,
    assert_every_project_file_is_accounted_for,
)

ROOT: Final = Path(__file__).resolve().parents[1]
DELTAS_FILE: Final = ROOT / 'tests' / '_famconfig_delta.py'
RERENDER: Final = 'python -m dev_lab.dev.famfiles --deltas tests/_famconfig_delta.py'


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
    path.write_text(path.read_text(encoding='utf-8').replace('htmlcov/\n', ''), encoding='utf-8')
    assert any(line.startswith('.gitignore: would render') for line in render_all(repo, rendered, write=False))
    render_all(repo, rendered, write=True)
    assert 'htmlcov/\n' in path.read_text(encoding='utf-8')
    assert 'scratch/' not in path.read_text(encoding='utf-8'), 'SCRATCH-IS-NEVER-COMMITTED: scratch stays visible'


def test_a_rendered_file_is_lf_on_every_os(tmp_path: Path) -> None:
    """Rendered bytes are identical across OSes: no CRLF, whatever the platform's text default."""
    rendered = {name: DELTAS[name] for name in DELTAS if BASES[name].mode == RENDERED}
    render_all(tmp_path, rendered, write=True)
    for name in rendered:
        assert b'\r\n' not in (tmp_path / name).read_bytes(), name


# ------------------------------------------------------------------- the renderers, derived from the one list


def test_the_renderers_are_derived_from_the_generated_rows() -> None:
    """2026-11-07: a relock left every generated file stale because no list said what renders them.

    Every generated row but the lock names the command that writes it; the set of renderers is read off
    those rows and from nowhere else.
    """
    assert {renderer.name for renderer in RENDERERS} == {
        'agent_guard', 'autodoors', 'ciworkflows', 'famfiles', 'hook_adoption', 'hook_install',
    }  # fmt: skip
    unrendered = {row.path for row in PROJECT_FILES.values() if row.generated and row.renderer is None}
    assert unrendered == {'uv.lock'}, 'the lock is the door`s, every other generated file names its renderer'


def test_a_renderer_is_due_where_a_file_it_writes_is_present(tmp_path: Path) -> None:
    """PLANTED CONTROL: a tree holding none of the generated files has no renderer due."""
    assert due_renderers(tmp_path) == ()
    (tmp_path / '.github' / 'workflows').mkdir(parents=True)
    (tmp_path / '.github' / 'workflows' / 'ci.yml').write_text('{}\n', encoding='utf-8')
    (tmp_path / '.gitignore').write_text('x\n', encoding='utf-8')
    assert {renderer.name for renderer in due_renderers(tmp_path)} == {'ciworkflows', 'famfiles'}


def test_a_renderers_command_reads_the_repos_render_table(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.render]\ndeltas = "tests/_d.py"\nshell_doors = ["a.sh", "b.sh"]\n', encoding='utf-8'
    )
    named = {renderer.name: renderer for renderer in RENDERERS}
    assert render_argv(named['famfiles'], tmp_path, 'py') == [
        'py', '-m', 'dev_lab.dev.famfiles', '--repo', str(tmp_path), '--deltas', 'tests/_d.py',
    ]  # fmt: skip
    assert render_argv(named['autodoors'], tmp_path, 'py')[-4:] == ['--shell-door', 'a.sh', '--shell-door', 'b.sh']
    assert render_argv(named['ciworkflows'], tmp_path, 'py') == [
        'py', '-m', 'dev_lab.dev.ciworkflows', 'render', '--root', str(tmp_path),
    ]  # fmt: skip


def test_a_due_renderer_missing_its_declared_input_is_refused_by_name(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same renderer with the key declared builds its command (above)."""
    named = {renderer.name: renderer for renderer in RENDERERS}
    with pytest.raises(ValueError, match=r'\[tool\.dev_lab\.render\] adoption'):
        render_argv(named['hook_adoption'], tmp_path, 'py')
