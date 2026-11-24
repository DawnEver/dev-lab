"""PROJECT-FILES-HAVE-ONE-SOURCE: the family list, the one renderer, and both famtests bodies -- each planted.

The kit runs both bodies on itself (it is an adopter like any other), and every refusal is driven over
a throwaway repository in ``tmp_path`` so a green here is a measurement and not a reader of nothing.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from _famconfig_delta import DELTAS, REPO

from dev_lab.dev.agentsection import AGENTS_REL, BEGIN, END, render_section
from dev_lab.dev.famconfig import BASES, RENDERED
from dev_lab.dev.famfiles import (
    MANAGED,
    OWNED,
    PROJECT_FILES,
    RENDERERS,
    RETIRED_PROJECT_FILES,
    due_renderers,
    is_member,
    main,
    managed_sections,
    project_files_on_disk,
    render_agent_files,
    render_all,
    render_argv,
    render_repo,
    unplaced_workflows,
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
    path.write_text(path.read_text(encoding='utf-8').replace('/dist/\n', ''), encoding='utf-8')
    assert any(line.startswith('.gitignore: would render') for line in render_all(repo, rendered, write=False))
    render_all(repo, rendered, write=True)
    assert '/dist/\n' in path.read_text(encoding='utf-8')
    assert 'scratch/' not in path.read_text(encoding='utf-8'), 'SCRATCH-IS-NEVER-COMMITTED: scratch stays visible'


def test_a_rendered_file_is_lf_on_every_os(tmp_path: Path) -> None:
    """Rendered bytes are identical across OSes: no CRLF, whatever the platform's text default."""
    rendered = {name: DELTAS[name] for name in DELTAS if BASES[name].mode == RENDERED}
    render_all(tmp_path, rendered, write=True)
    for name in rendered:
        assert b'\r\n' not in (tmp_path / name).read_bytes(), name


def test_famfiles_writes_the_agents_section_and_keeps_the_repo_text(tmp_path: Path) -> None:
    """The family section is spliced between its markers; the repo's own text around it is kept.

    PLANTED CONTROL: a hand edit inside the markers reads drifted in check mode and current after one render.
    """
    (tmp_path / AGENTS_REL).write_text('# repo\n\nOur own rules.\n', encoding='utf-8')
    assert render_agent_files(tmp_path, write=False) == (f'{AGENTS_REL}: would render (drifted)',)
    assert render_agent_files(tmp_path, write=True) == (f'{AGENTS_REL}: rendered',)
    text = (tmp_path / AGENTS_REL).read_text(encoding='utf-8')
    assert text.startswith('# repo\n\nOur own rules.\n')
    assert render_section() in text
    (tmp_path / AGENTS_REL).write_text(text.replace('## Family workflow', '## My workflow'), encoding='utf-8')
    assert render_agent_files(tmp_path, write=False) == (f'{AGENTS_REL}: would render (drifted)',)
    render_agent_files(tmp_path, write=True)
    assert render_agent_files(tmp_path, write=False) == (f'{AGENTS_REL}: current',)
    assert (tmp_path / AGENTS_REL).read_text(encoding='utf-8') == text


#: Retired 2026-11-24 (user ruling): no family row, no renderer, no requirement -- each refused by name.
_RETIRED: Final = ('.claude/rem.json', '.rgignore', 'ruff.toml')


def test_the_retired_project_files_are_registered_and_have_no_row() -> None:
    """RETIRED-NAMES-REGISTERED: a retired file is named with its reason, and no row or base still writes it."""
    assert set(_RETIRED) <= set(RETIRED_PROJECT_FILES)
    assert all(why.strip() for why in RETIRED_PROJECT_FILES.values())
    assert not set(RETIRED_PROJECT_FILES) & set(PROJECT_FILES)
    assert not set(RETIRED_PROJECT_FILES) & set(BASES)
    assert PROJECT_FILES['Makefile'].kind == OWNED, 'the Makefile is the repo`s: no family contract any more'


@pytest.mark.parametrize('path', _RETIRED)
def test_a_tracked_retired_file_is_refused_by_name(repo: Path, path: str) -> None:
    """PLANTED CONTROL: the retired file committed again reds with its reason, owned or not."""
    assert_every_project_file_is_accounted_for(root=repo, owned_here={})
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text('{}\n', encoding='utf-8')
    _git('add', '-f', path, cwd=repo)
    with pytest.raises(AssertionError, match=f'{re.escape(path)}: RETIRED'):
        assert_every_project_file_is_accounted_for(root=repo, owned_here={})


# ------------------------------------------------------------------- the renderers, derived from the one list


def test_the_renderers_are_derived_from_the_generated_rows() -> None:
    """2026-11-07: a relock left every generated file stale because no list said what renders them.

    Every generated row but the lock names the command that writes it; the set of renderers is read off
    those rows and from nowhere else.
    """
    assert {renderer.name for renderer in RENDERERS} == {
        'agent_guard', 'autodoors', 'ciworkflows', 'claudesettings', 'famfiles', 'hook_adoption', 'vscodesettings',
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
        'py', '-m', 'dev_lab.dev.famfiles', '--files', '--repo', str(tmp_path), '--deltas', 'tests/_d.py',
    ]  # fmt: skip
    assert render_argv(named['autodoors'], tmp_path, 'py')[-4:] == ['--shell-door', 'a.sh', '--shell-door', 'b.sh']
    assert render_argv(named['ciworkflows'], tmp_path, 'py') == [
        'py', '-m', 'dev_lab.dev.ciworkflows', 'render', '--root', str(tmp_path),
    ]  # fmt: skip


def test_a_repo_without_a_deltas_module_renders_its_agents_section_and_no_base(tmp_path: Path) -> None:
    """2026-11-13: cc-market has no deltas module, so the one door refused it. No deltas = no per-file overrides.

    PLANTED CONTROL: the door without ``--files`` is still the one door, not this renderer.
    """
    named = {renderer.name: renderer for renderer in RENDERERS}
    assert render_argv(named['famfiles'], tmp_path, 'py') == [
        'py', '-m', 'dev_lab.dev.famfiles', '--files', '--repo', str(tmp_path),
    ]  # fmt: skip
    (tmp_path / '.gitignore').write_text('mine', encoding='utf-8')
    assert main(['--files', '--repo', str(tmp_path)]) == 0
    assert (tmp_path / '.gitignore').read_text(encoding='utf-8') == 'mine', 'no delta: the base is not written'
    assert all(text in (tmp_path / rel).read_text(encoding='utf-8') for rel, text in managed_sections())
    assert main(['--files', '--check', '--repo', str(tmp_path)]) == 0
    with pytest.raises(SystemExit):
        main(['--check', '--repo', str(tmp_path)])  # the door itself: --check reads one renderer


def test_a_due_renderer_missing_its_declared_input_is_refused_by_name(tmp_path: Path) -> None:
    """PLANTED CONTROL: the same renderer with the key declared builds its command (above)."""
    named = {renderer.name: renderer for renderer in RENDERERS}
    with pytest.raises(ValueError, match=r'\[tool\.dev_lab\.render\] adoption'):
        render_argv(named['hook_adoption'], tmp_path, 'py')


# ------------------------------------------------------------------- the one door: every declared artefact


def _declare(root: Path, table: str) -> None:
    (root / 'pyproject.toml').write_text(f'[tool.dev_lab.render]\n{table}', encoding='utf-8')


def test_the_one_door_runs_every_due_renderer_with_its_declared_inputs(tmp_path: Path) -> None:
    """``famfiles`` without ``--deltas`` is the one door: every renderer due, its inputs from the render table.

    2026-11-13: agents ran ciworkflows, famfiles, hook_adoption and agent_guard one by one, and famfiles ignored
    the declared ``adoption``. PLANTED CONTROL: the same repo minus its hook rules file runs no hook_adoption.
    """
    hooks = tmp_path / '.claude' / 'hooks'
    hooks.mkdir(parents=True)
    (hooks / 'deny-rules.json').write_text('{}\n', encoding='utf-8')
    (tmp_path / '.gitignore').write_text('x\n', encoding='utf-8')
    _declare(tmp_path, 'deltas = "d.py"\nadoption = "scripts/deny_rules.py"\n')
    ran: list[list[str]] = []
    lines = render_repo(tmp_path, 'py', lambda argv, _root: ran.append(argv) or 0)
    assert [line.split(':')[0] for line in lines if line.endswith(': rendered')] == [
        'famfiles', 'claudesettings', 'agent_guard', 'hook_adoption', 'autodoors', 'vscodesettings', 'ciworkflows',
    ]  # fmt: skip
    assert ran[3][-2:] == ['--adoption', 'scripts/deny_rules.py']
    (hooks / 'deny-rules.json').unlink()
    _declare(tmp_path, 'deltas = "d.py"\n')
    assert 'hook_adoption: skipped -- [tool.dev_lab.render] adoption is not declared' in render_repo(
        tmp_path, 'py', lambda _argv, _root: 0
    )
    with pytest.raises(ValueError, match='the renderer famfiles exited 3'):
        render_repo(tmp_path, 'py', lambda _argv, _root: 3)


def test_a_family_repo_with_no_render_table_gets_its_workflows(tmp_path: Path) -> None:
    """2026-11-13: cc-market declared only ``[tool.dev_lab.integrator]``; the door rendered nothing, silently.

    PLANTED CONTROL: the same tree without the table is no family repo, and every renderer says why it skipped.
    """
    ran: list[list[str]] = []
    lines = render_repo(tmp_path, 'py', lambda argv, _root: ran.append(argv) or 0)
    assert ran == []
    assert len(lines) == len(RENDERERS)
    assert all(': skipped -- not a family repo' in line or 'is not declared' in line for line in lines)
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.integrator]\nintegration = "main"\n', encoding='utf-8')
    lines = render_repo(tmp_path, 'py', lambda argv, _root: ran.append(argv) or 0)
    assert 'ciworkflows: rendered' in lines
    assert ['py', '-m', 'dev_lab.dev.ciworkflows', 'render', '--root', str(tmp_path)] in ran
    assert 'hook_adoption: skipped -- [tool.dev_lab.render] adoption is not declared' in lines


@pytest.mark.parametrize(
    ('manifest', 'member'),
    [
        ('[project]\ndependencies = ["dev-lab[test]>=1"]\n', True),
        ('[dependency-groups]\ndev = [{ include-group = "x" }, "dev_lab"]\n', True),
        ('[project.optional-dependencies]\ndev = ["Dev.Lab"]\n', True),
        ('[tool.dev_lab.ci]\n"ci.yml" = {}\n', True),
        ('[project]\ndependencies = ["dev-labyrinth", "lab-commons"]\n', False),  # the control
        ('', False),
    ],
)
def test_a_repo_is_a_family_member_by_its_dev_lab_dependency_or_table(manifest: str, *, member: bool) -> None:
    assert is_member(manifest) is member


def test_the_guard_waits_for_the_deny_rules_it_installs_over(tmp_path: Path) -> None:
    """agent_guard --install exits 1 without deny rules, so a family repo not adopting them skips it, by name.

    PLANTED CONTROL: declaring the adoption makes both due.
    """
    _declare(tmp_path, 'deltas = "d.py"\n')
    lines = render_repo(tmp_path, 'py', lambda _argv, _root: 0)
    skipped = 'agent_guard: skipped -- it needs hook_adoption, skipped: [tool.dev_lab.render] adoption is not declared'
    assert skipped in lines
    _declare(tmp_path, 'adoption = "a.py"\n')
    assert {'agent_guard: rendered', 'hook_adoption: rendered'} <= set(render_repo(tmp_path, 'py', lambda _a, _r: 0))


def test_the_module_door_runs_and_its_check_says_no_to_a_stale_file(tmp_path: Path) -> None:
    """2026-11-13: ``python -m dev_lab.dev.famfiles`` had no ``__main__`` guard: a check that could not say no.

    Every invocation -- the door, ``--files``, ``--check`` -- imported the module, printed nothing and exited 0.

    PLANTED CONTROL: a stale family section makes ``--check`` exit 1; after the render it exits 0.
    """
    door = [sys.executable, '-m', 'dev_lab.dev.famfiles', '--files', '--repo', str(tmp_path)]
    page = tmp_path / AGENTS_REL
    page.write_text(f'{BEGIN}\nstale\n{END}\n', encoding='utf-8')
    checked = subprocess.run([*door, '--check'], capture_output=True, text=True, encoding='utf-8', check=False)
    assert checked.returncode == 1
    assert f'{AGENTS_REL}: would render (drifted)' in checked.stdout
    assert subprocess.run(door, capture_output=True, check=False).returncode == 0
    assert page.read_text(encoding='utf-8') == render_section()
    again = subprocess.run([*door, '--check'], capture_output=True, text=True, encoding='utf-8', check=False)
    assert (again.returncode, f'{AGENTS_REL}: current' in again.stdout) == (0, True)


def test_a_workflow_is_kept_only_where_the_ci_declaration_places_it(repo: Path) -> None:
    """A workflow is kept only where the ci declaration places it (user ruling 2026-11-24, item 4).

    A base workflow on the repo's forge is accounted; a hand-written one and
    one placed for the other forge are refused by name. PLANTED CONTROL: the same name declared is accepted.
    """
    workflows = repo / '.github' / 'workflows'
    workflows.mkdir(parents=True)
    for name in ('ci.yml', 'hand.yml'):
        (workflows / name).write_text('x\n', encoding='utf-8')
    (repo / '.gitea' / 'workflows').mkdir(parents=True)
    (repo / '.gitea' / 'workflows' / 'merge.yml').write_text('x\n', encoding='utf-8')
    forge = '[project]\nname = "x"\n\n[tool.dev_lab.ci."ci.yml"]\nforge = "github"\n'
    (repo / 'pyproject.toml').write_text(forge, encoding='utf-8')
    _git('add', '.', cwd=repo)
    assert unplaced_workflows(repo) == ('.gitea/workflows/merge.yml', '.github/workflows/hand.yml')
    with pytest.raises(AssertionError, match=r'hand\.yml: a workflow no \[tool\.dev_lab\.ci\] table places'):
        assert_every_project_file_is_accounted_for(root=repo, owned_here={})
    (repo / 'pyproject.toml').write_text(f'{forge}\n[tool.dev_lab.ci."hand.yml"]\nforge = "github"\n', encoding='utf-8')
    assert unplaced_workflows(repo) == ('.gitea/workflows/merge.yml',)
