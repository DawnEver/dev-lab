"""Workflows are TOML rendered to bytes: this repo's files ARE the render, and a hand edit is refused.

Nothing here parses YAML -- the comparison is between rendered bytes and file bytes.
"""

from __future__ import annotations

from pathlib import Path

from dev_lab.dev.ciworkflows import RENDER_COMMAND, STAMP, drift, main, merge, render, workflows, write

_ROOT = Path(__file__).resolve().parents[1]


def test_this_repo_s_workflows_are_exactly_their_render() -> None:
    assert set(workflows(_ROOT)) == {'ci.yml', 'python-verify.yml'}, 'a floor: an empty table drifts from nothing'
    assert drift(_ROOT) == []


def test_a_repo_opts_in_and_its_layer_merges_over_the_base(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text(
        '[tool.dev_lab.ci."ci.yml".jobs.verify.with]\nextras = "dev"\n', encoding='utf-8'
    )
    ci = workflows(tmp_path)['ci.yml']
    assert ci['jobs']['verify']['with'] == {'python-versions': '["3.12", "3.13"]', 'extras': 'dev'}
    assert ci['jobs']['verify']['uses'].startswith('DawnEver/lab-commons/')


def test_a_repo_that_declares_nothing_renders_nothing(tmp_path: Path) -> None:
    (tmp_path / 'pyproject.toml').write_text('', encoding='utf-8')
    assert workflows(tmp_path) == {}
    assert write(tmp_path) == []


def test_a_hand_edit_and_a_hand_written_workflow_are_refused_naming_the_render(tmp_path: Path, capsys) -> None:
    """PLANTED CONTROL: render, then edit one byte and add an undeclared file -- both must be named."""
    (tmp_path / 'pyproject.toml').write_text('[tool.dev_lab.ci."ci.yml"]\n', encoding='utf-8')
    write(tmp_path)
    assert main(['check', '--root', str(tmp_path)]) == 0
    path = tmp_path / '.github' / 'workflows' / 'ci.yml'
    path.write_text(path.read_text(encoding='utf-8').replace('"CI"', '"Ci"'), encoding='utf-8')
    (path.parent / 'extra.yml').write_text('name: x\n', encoding='utf-8')
    assert main(['check', '--root', str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert 'ci.yml: differs' in out
    assert 'extra.yml: a workflow no' in out
    assert RENDER_COMMAND in out


def test_the_render_is_a_stamp_then_json() -> None:
    text = render({'name': 'x', 'on': {'push': {}}})
    assert text.startswith(f'{STAMP}\n{{\n')
    assert text.endswith('}\n')


def test_merge_replaces_a_non_table_and_merges_a_table() -> None:
    assert merge({'a': {'b': 1, 'c': [1]}}, {'a': {'c': [2]}}) == {'a': {'b': 1, 'c': [2]}}
